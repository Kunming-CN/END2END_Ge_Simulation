"""Small synthetic fixtures only; never reads .local/m2c or runs Julia."""
import copy
import csv
import json
import math
from pathlib import Path
import statistics
import tempfile
import unittest
from unittest.mock import patch

import lithium_report as li

AUDIT = 'model,event_id,raw_row_index,species,energy_keV,original_keV,no_trapping_keV,conditional_remainder_keV,endpoint_W,end_time_ns,region,geometric_contact,at_step_limit,exactly_zero_E,stationary,source_match'
SCAN = 'grid_case,depth_mm,dt_ns,horizon_ns,seed,n,diffusion,mean,sem,no_trapping_mean,no_trapping_sem,integrity_pass'
PROFILE = 'grid_case,depth_mm,E_V_cm,W,donor_cm3,net_cm3,mu_e_m2_V_s,mu_h_m2_V_s,D_e_m2_s,D_h_m2_s,nearest_bits,impurity_scale,region'


def deposit(value=-.2, energy=1, parcel=1):
    ends = {s: dict(flags={k: k in ('stationary', 'exactly_zero_E', 'at_step_limit') for k in li.FLAGS},
                   noncontact_outer_points=0, weighting_potential=w, end_time_ns=5000,
                   region='p-nearest-undepleted-inactive-bit') for s, w in (('electron', 0), ('hole', value + .1))}
    return dict(energy_keV=energy, endpoints=ends, original_fraction=value, no_trapping_fraction=value + .1,
                original_final_keV=energy * value, no_trapping_final_keV=energy * (value + .1),
                ramo_pass=True, path_integrity_pass=True, ramo_error=0., parcel_id=parcel,
                derived_seed=1000 * li.SEEDS[0] + parcel, source_match=True, raw_row_index=1,
                conditional_remainder_keV=energy * (1 - value - .1), absolute_component_sum_keV=energy * abs(1 - value - .1))


def cloud(grid, depth, dt, horizon, seed, diffusion):
    value = [-.2, .1, .4][li.SEEDS.index(seed)] + (1 if grid == 'contrast25' else 0)
    n = 32 if diffusion else 1
    rows = [deposit(value, 1 / n, j) for j in range(1, n + 1)]
    stats = lambda v: dict(mean=v, sem=0. if diffusion else None, n=n, minimum=v, maximum=v, outside_unit_range=n if not 0 <= v <= 1 else 0)
    return dict(grid_case=grid, depth_mm=depth, dt_ns=dt, horizon_ns=horizon, seed=seed,
                diffusion=diffusion, end_drift_when_no_field=not diffusion, self_repulsion=False,
                total_energy_keV=1., numerical_parcels=n, parcels=rows, original_stats=stats(value),
                no_trapping_stats=stats(value + .1), summary=li.endpoints(rows), integrity_pass=True,
                runtime_s=.01, mean_trace=dict(time_ns=[0, horizon], original_fraction=[-0., value]))


class LithiumReportTests(unittest.TestCase):
    def setUp(self):
        local = li.ROOT / '.local'
        local.mkdir(exist_ok=True)
        self.tmp = tempfile.TemporaryDirectory(prefix='lithium-test-', dir=local)
        self.root = Path(self.tmp.name).resolve()
        self.assertTrue(self.root.is_relative_to(local.resolve()))
        self.addCleanup(self.tmp.cleanup)
        for module in (li, li.common):
            p = patch.object(module, 'ROOT', self.root)
            p.start()
            self.addCleanup(p.stop)
        self.source = self.root / '.local' / 'input'
        self.source.mkdir(parents=True)
        names = ['simulation/' + n for n in ('diagnose_lithium.jl', 'test_lithium.jl', 'diagnose_collection.jl', 'run.jl', 'replay.jl', 'readout.jl', 'readout_demo.json', 'Project.toml', 'Manifest.toml')]
        names += ['models/AK02.yaml', 'models/SAP22.yaml']
        for name in names:
            p = self.root / name
            p.parent.mkdir(exist_ok=True)
            p.write_text('fixture ' + name)
        pins = {m: li.common.sha256(self.root / 'models' / (m + '.yaml')) for m in li.PINS}
        p = patch.object(li, 'PINS', pins)
        p.start()
        self.addCleanup(p.stop)
        self.report = dict(schema_version=1, kind='native_lithium_diagnostics', status='completed_diagnostics_only', phase='all',
            source_hashes={Path(n).name: li.common.sha256(self.root / n) for n in names[:3]},
            producer_sources={n: li.common.sha256(self.root / n) for n in names[3:]},
            input_artifacts={f'{m}/{n}': 'a' * 64 for m in pins for n in ('transport/events.json', 'charge/run.json', 'charge/signals.csv', 'readout/run.json')},
            input_run_sha256='b' * 64, sdk_source_pins={'Event/Event.jl': 'c' * 64}, environment={'julia_version': 'fixture'},
            fixed_work=dict(depths_mm=li.DEPTHS, seeds=li.SEEDS, grid_cases=li.GRIDS, parcels_per_seed=32, max_primaries_per_model=100,
                            max_positive_deposits_per_model=2048, diffusive_clouds=63, no_diffusion_controls=9, default_dt_ns=2, default_horizon_ns=5000),
            units={'energy': 'keV'}, limitations=['Synthetic test fixture.'], runtime_s=1., cases=[])
        for model, grid in [('AK02', 'baseline'), ('SAP22', 'baseline'), ('AK02', 'contrast50'), ('AK02', 'contrast25')]:
            _, spacing, rechecks = next(g for g in li.GRIDS if g[0] == grid)
            item = dict(model=model, case=grid, model_sha256=pins[model], min_grid_mm=spacing, rechecks=rechecks,
                        cfg={'dt': 2.}, field_attempt_wall_seconds=.1, compensation_depth_mm=.55)
            if grid == 'baseline':
                item.update(events=[dict(event_id=j, source_match=True, deposits=[deposit()] if j == 0 else [],
                            raw_steps=[dict(raw_row_index=1, energy_keV=1)] if j == 0 else [],
                            source_charge_report=dict(raw_rows=int(j == 0), charge_deposits=int(j == 0), steps=[{}] if j == 0 else [])) for j in range(100)],
                            integrity_pass=True, differences=[], summary=dict(primary_count=100, deposits=1, zero_deposit_primaries=99))
            if model == 'AK02':
                keys = []
                if grid == 'baseline':
                    keys += [(d, 2, 5000, li.SEEDS[0], False) for d in li.DEPTHS]
                    keys += [(d, 2, 5000, s, True) for d in li.DEPTHS for s in li.SEEDS]
                    keys += [(d, dt, h, s, True) for d in (.3, .55, .8) for s in li.SEEDS for dt, h in ((4, 5000), (2, 10000))]
                else:
                    keys += [(d, 2, 5000, s, True) for d in (.5, .55, .6) for s in li.SEEDS]
                item['clouds'] = [cloud(grid, *key) for key in keys]
            self.report['cases'].append(item)
        self.report['sensitivities'] = []
        for kind, depths in [('time_step', (.3, .55, .8))]:
            for d in depths:
                for s in li.SEEDS:
                    for k in (kind, 'horizon'):
                        for signal in ('original_stats', 'no_trapping_stats'):
                            self.report['sensitivities'].append(dict(kind=k, depth_mm=d, seed=s, signal=signal, absolute_difference=0., prospective_gate=.03, passed=True))
        for d in (.5, .55, .6):
            for s in li.SEEDS:
                for signal in ('original_stats', 'no_trapping_stats'):
                    self.report['sensitivities'].append(dict(kind='grid', depth_mm=d, seed=s, signal=signal, absolute_difference=1., prospective_gate=.03, passed=False))
        self.report['sensitivity_all_passed'] = False

    def write_fixture(self):
        tables = {name: [] for name in li.FILES[1:]}
        for i in self.report['cases']:
            for e in i.get('events', []):
                for r in e['deposits']:
                    for s, end in r['endpoints'].items():
                        tables['endpoint-audit.csv'].append([i['model'], e['event_id'], r['raw_row_index'], s, r['energy_keV'], r['original_final_keV'], r['no_trapping_final_keV'], r['conditional_remainder_keV'], end['weighting_potential'], end['end_time_ns'], end['region'], *[end['flags'][k] for k in li.FLAGS[:4]], True])
            for c in i.get('clouds', []):
                a, b = c['original_stats'], c['no_trapping_stats']
                tables['depth-scan.csv'].append([c[k] for k in ('grid_case', 'depth_mm', 'dt_ns', 'horizon_ns', 'seed', 'numerical_parcels', 'diffusion')] + [a['mean'], a['sem'], b['mean'], b['sem'], c['integrity_pass']])
            if i['model'] == 'AK02':
                tables['profiles.csv'] += [[i['case'], j * .002, j * .1, .5, 1, -1, .1, .1, .01, .01, 1, -0., 'p-nearest-depleted-no-inactive-bit'] for j in range(501)]
        for name, header in zip(li.FILES[1:], (AUDIT, SCAN, PROFILE)):
            with (self.source / name).open('w', newline='') as stream:
                writer = csv.writer(stream)
                writer.writerow(header.split(','))
                writer.writerows([str(v).lower() if isinstance(v, bool) else 'nothing' if v is None else v for v in row] for row in tables[name])
        (self.source / 'report.json').write_text(json.dumps(self.report), encoding='utf-8')

    def run_export(self, name='view'):
        self.write_fixture()
        return li.export(self.source, self.source.parent / name)

    def test_complete_signed_sem_and_offline(self):
        self.report['cases'][0]['clouds'][0]['runtime_s'] = -0.0
        data = self.run_export()
        output = self.source.parent / 'view'
        self.assertEqual(set(p.name for p in output.iterdir()), {'lithium.html', 'summary.json', *li.FILES[1:]})
        self.assertNotIn('transition_grid', data)
        self.assertEqual(len(data['clouds']), 72)
        self.assertEqual(data['clouds'][0]['original_stats']['mean'], -.2)
        self.assertAlmostEqual(data['seed_means'][0]['original']['mean'], .1)
        self.assertAlmostEqual(data['seed_means'][0]['original']['seed_sem'], statistics.stdev([-.2, .1, .4]) / math.sqrt(3))
        page = (output / 'lithium.html').read_text(encoding='utf-8')
        for text in ('Sensitivity screens failed: 18 / 54', 'Not converged', '200 original primaries', 'Nseeds=3', 'geometric_contact'):
            self.assertIn(text, page)
        for forbidden in ('<script', 'cdn', 'src="http', self.root.as_posix()):
            self.assertNotIn(forbidden, page)
        self.assertNotIn('parcels', data['clouds'][0])
        self.assertNotIn('events', data['cases'][0])
        for name in li.FILES[1:]:
            self.assertEqual((output / name).read_bytes(), (self.source / name).read_bytes())
        self.assertEqual(li.common.load_json(output / 'summary.json'), data)
        self.assertEqual(math.copysign(1, li.common.load_json(output / 'summary.json')['clouds'][0]['runtime_s']), -1)
        self.assertIn('-0.0', (output / 'summary.json').read_text())

    def test_status_hash_counts_and_integrity_refused(self):
        original = copy.deepcopy(self.report)
        mutations = [lambda r: r.update(status='running'), lambda r: r['source_hashes'].update({'diagnose_lithium.jl': '0' * 64}),
                     lambda r: r['producer_sources'].update({'simulation/replay.jl': '0' * 64}), lambda r: r['cases'][0]['events'].pop(),
                     lambda r: r['cases'][0]['clouds'].pop(), lambda r: r['cases'][0]['clouds'][0]['parcels'][0].update(ramo_pass=False),
                     lambda r: r['cases'][0]['clouds'][0]['parcels'][0].update(path_integrity_pass=False),
                     lambda r: r['cases'][0]['events'][0]['raw_steps'].clear(),
                     lambda r: r['fixed_work'].update(diffusive_clouds=62),
                     lambda r: r['cases'][0]['clouds'][0]['original_stats'].update(mean=float('inf')),
                     lambda r: r.update(sensitivity_all_passed=True), lambda r: r['sensitivities'][0].update(passed=False),
                     lambda r: r['cases'][0].update(model_sha256='0' * 64)]
        for change in mutations:
            with self.subTest(change=change):
                self.report = copy.deepcopy(original)
                change(self.report)
                with self.assertRaises((ValueError, KeyError)):
                    self.run_export()
                self.assertFalse((self.source.parent / 'view').exists())

    def test_missing_file_csv_disagreement_and_nonfinite(self):
        self.write_fixture()
        (self.source / 'profiles.csv').unlink()
        with self.assertRaises(FileNotFoundError):
            li.export(self.source, self.source.parent / 'view')
        self.write_fixture()
        p = self.source / 'depth-scan.csv'
        p.write_text(p.read_text().replace('-0.2', '-0.25', 1))
        with self.assertRaisesRegex(ValueError, 'CSV/report'):
            li.export(self.source, self.source.parent / 'view')
        for bad in ('NaN', 'Infinity', '1e999', '-inf'):
            with self.assertRaises(ValueError):
                li.csv_rows(('x\n' + bad + '\n').encode())
        with self.assertRaisesRegex(ValueError, 'CSV schema'):
            li.csv_rows(b'wrong_header\n', 'endpoint-audit.csv')

    def test_phase_claims(self):
        original = copy.deepcopy(self.report)
        self.report.update(phase='audit', cases=self.report['cases'][:2])
        self.report.pop('sensitivities')
        for case in self.report['cases']:
            case.pop('clouds', None)
        self.run_export('audit')
        self.assertIn('no depth/sensitivity scan performed', (self.source.parent / 'audit/lithium.html').read_text(encoding='utf-8'))
        self.report = original
        self.report['phase'] = 'depth'
        self.report['cases'] = [i for i in self.report['cases'] if i['model'] == 'AK02']
        for i in self.report['cases']:
            i.pop('events', None)
        self.run_export('depth')
        self.assertIn('no original-event audit performed', (self.source.parent / 'depth/lithium.html').read_text(encoding='utf-8'))

    def test_new_local_output_only(self):
        self.run_export()
        for path in (self.source.parent / 'view', self.root / 'escape', self.source / 'nested', self.source.parent / '..' / '..' / 'escape'):
            with self.subTest(path=path), self.assertRaises(ValueError):
                li.export(self.source, path)

    def test_postrun_seed_equivalence_is_separate(self):
        samples = [cloud(grid, .5, 2, 5000, seed, True)
                   for grid in ('contrast50', 'contrast25') for seed in li.SEEDS]
        result = li.seed_equivalence(samples)
        self.assertEqual(len(result), 2)
        self.assertTrue(all(not r['inside_0p02'] for r in result))
        self.assertTrue(all(abs(r['mean_difference'] - 1) < 1e-12 for r in result))
        for c in samples:
            if c['grid_case'] == 'contrast25':
                for key in ('original_stats', 'no_trapping_stats'):
                    c[key]['mean'] -= 1
        self.assertTrue(all(r['inside_0p02'] for r in li.seed_equivalence(samples)))
        with self.assertRaises(ValueError):
            li.seed_equivalence(samples[:-1])

    def test_bundle_validation_detects_csv_and_html_mutation(self):
        self.run_export()
        output = self.source.parent / 'view'
        self.assertEqual(li.validate_bundle(output)['schema_version'], 1)
        csvfile = output / 'depth-scan.csv'
        original = csvfile.read_bytes()
        csvfile.write_bytes(original + b'changed')
        with self.assertRaisesRegex(ValueError, 'CSV changed'):
            li.validate_bundle(output)
        csvfile.write_bytes(original)
        page = output / 'lithium.html'
        page.write_bytes(page.read_bytes() + b'changed')
        with self.assertRaisesRegex(ValueError, 'HTML differs'):
            li.validate_bundle(output)

    def grid_fixture(self):
        source = self.root / 'simulation'
        pins = {n: li.common.sha256(source / n) for n in ('Project.toml', 'Manifest.toml')}
        declaration = lambda d: ','.join(f'"{k}"=>"{v}"' for k, v in d.items())
        legacy = source / 'diagnose_lithium.jl'
        legacy.write_text('const PINNED=Dict(' + declaration(pins) + ')\nconst SDK_PINS=Dict("Event/Event.jl"=>"' + 'c'*64 + '")\nrequire=C.require\n')
        self.report['source_hashes'][legacy.name] = li.common.sha256(legacy)
        project = {n: li.common.sha256(source / n) for n in ('run.jl', legacy.name)}
        (source / 'diagnose_transition_grid.jl').write_text('const SOURCE_PINS=Dict(' + declaration(project) + ')\nconst NATIVE_PINS=merge(L.SDK_PINS,Dict("Native.jl"=>"' + 'd'*64 + '"))\nconst HISTORICAL_REPORT_SHA="' + 'b'*64 + '"')
        (source / 'test_transition_grid.jl').write_text('fixture tests')
        project.update({n: li.common.sha256(source / n) for n in ('diagnose_transition_grid.jl', 'test_transition_grid.jl')})
        grid = self.source.parent / 'grid'
        grid.mkdir()
        (grid / 'profiles.csv').write_text('case,stage,depth_mm,E_V_cm,W,alpha,point_bits,net_impurity_cm3\nmin50,initial,0,0,0,0,1,1\nmin50,initial,0.5,1,0.5,0.5,1,1\nmin50,initial,1,2,1,1,1,1\n')
        (grid / 'smallcomparisons.csv').write_text('reference,candidate,normalized_E,onset0_shift_mm,onset1_shift_mm,max_W,passed\n')
        g = dict(schema_version=1, kind='AK02_native_transition_grid', phase='all', status='nested_blocked_baseline_defects_or_failure',
            held_settings=dict(temperature_K=77, bias_V=500, precision='Float64', sor=1, threads=2, max_grid_mm=2, profile_relative_gate=.01, onset_gate_mm=.002,
                               limits=dict(V=5e-6, W=1e-8, seconds=900, points=250000, initial=20000, extra=20000)),
            provenance=dict(sources=project, native_sources={'Event/Event.jl': 'c'*64, 'Native.jl': 'd'*64}, model_sha256=li.PINS['AK02'],
                            environment=dict(project='simulation/Project.toml', environment_manifest_sha256=pins['Manifest.toml'])),
            cases=[dict(case='min50', status='budget_failed', failure=None, E_accepted=False, W_accepted=False,
                E_grid=dict(shape=[3, 1, 3], ticks_m_rad_m=[[0, .5, 1], [0], [0, .5, 1]]),
                E_checks=[dict(frozen=dict(max=.1), full_sweep=dict(potential=.2), poisson=dict(max=.3), sweeps=20000)],
                W_checks=[dict(frozen=dict(max=.1), full_sweep=dict(potential=.2), poisson=None, sweeps=0)],
                initial=dict(samples=[dict(depth_mm=.5, E_V_cm=1, W=.5)], target_spacings_um=[86.607, 100], onsets_0_1_V_cm=[[0, .5], [.5, 1]]))],
            comparisons=[], baseline_accepted=False, limitations=['Fixture, no CCE claim.'], runtime_seconds=1,
            artifacts={n: li.common.sha256(grid / n) for n in li.GRID_FILES.values()})
        return grid, g

    def axes_fixture(self):
        _, grid = self.grid_fixture()
        source = self.root / 'simulation'
        inventory = {'Grids/fixture.jl': li.hashlib.sha256(b'synthetic native inventory').hexdigest()}
        tree = li.hashlib.sha256('\n'.join(n+' '+h for n, h in sorted(inventory.items())).encode()).hexdigest()
        path = source / 'diagnose_transition_grid.jl'; path.write_text(path.read_text() + '\nconst NATIVE_TREE_SHA="' + tree + '"')
        grid['provenance']['native_sources'].update(inventory); grid['provenance']['native_tree_sha256'] = tree
        grid['provenance']['sources'][path.name] = li.common.sha256(path)
        (self.source.parent / 'grid/report.json').write_text(json.dumps(grid))
        helpers = {n: li.common.sha256(source / n) for n in ('diagnose_transition_grid.jl', 'test_transition_grid.jl')}
        (source / 'diagnose_transition_axes.jl').write_text('const TRANSITION_AXES_HELPERS=Dict(' + ','.join(f'"{n}"=>"{h}"' for n, h in helpers.items()) + ')\nfor (n,h) in TRANSITION_AXES_HELPERS\n')
        (source / 'test_transition_axes.jl').write_text('synthetic axes tests')
        sources = {n: li.common.sha256(source / n) for n in (*helpers, 'diagnose_transition_axes.jl', 'test_transition_axes.jl')}
        self.axes = self.source.parent / 'axes'; self.axes.mkdir()
        g = dict(schema_version=1, kind='AK02_transition_axes', status='completed_attribution_diagnostics', final_sources_unchanged=True, expected_case_count=7,
                 runtime_seconds=7, held_settings=dict(temperature_K=77, bias_V=500, threads=2, precision='Float64', sor=1., fresh_sweeps=40000, continuation_sweeps=20000, case_seconds=900., node_cap=250000, seed='none: deterministic'),
                 provenance=dict(sources=sources, Tprovenance=grid['provenance']), baseline_accepted=True, cases=[], comparisons=[], unavailable_comparisons=[], limitations=['Synthetic numerical fixture; no physics run.'])
        profile = dict(samples=2001, csv_stage='final', target_spacings_um=[100, 100], onsets_0_1_V_cm=[[0, .0005], [.5, .5005]], **{'E0.5_V_cm': 1.})
        ticks = dict(shape=[3, 1, 4], ticks_m_rad_m=[[.01205, .01215, .01225], [0], [.0046, .0047, .0048, .0049]])
        native_hashes = {k: 'a'*64 for k in ('potential', 'imp_scale', 'point_types', 'q_eff_imp', 'q_eff_fix', '\u03f5_r')}
        identity = {k: 'a'*64 for k in ('q_eff_imp', 'q_eff_fix', '\u03f5_r', 'volume_weights', 'sor_const', 'point_types', 'imp_scale')}
        identity.update(grid=ticks, geom_weights=['b'*64]*3, axis_bytes=['c'*64]*3)
        for name in li.AXES_CASES:
            checks = [dict(frozen=dict(max=0., max_alpha_voltage=0.), poisson=dict(max=0.), full_sweep=dict(potential=0., alpha_voltage=0.), sweeps=j*500, elapsed_seconds=j, consecutive_passes=j+1) for j in range(2)]
            native = dict(case=name, E_accepted=True, E_checks=checks, E_geometric_contacts=[dict(nodes=1, max_error=0.)], E_grid=copy.deepcopy(ticks), E_repaint=dict(max_change=0.), E_final_repaint=dict(max_change=0.), E_final_native_hashes=copy.deepcopy(native_hashes))
            g['cases'].append(dict(case=name, nativeitem=native, status='accepted_fixed_grid', profile=copy.deepcopy(profile), final_profile=copy.deepcopy(profile), elapsed_seconds=1., within_cooperative_time_budget=True, initial_identity=copy.deepcopy(identity), inputVhash='e'*64, rebuild_identity_verified=True, independent_parent_storage_verified=True, parent_before={'potential': 'f'*64}, parent_after={'potential': 'f'*64}))
            if name not in li.AXES_CASES[:2]: g['cases'][-1]['initial_potential_source'] = 'min25' if name == 'g22_from25' else 'min50'
        # Signed components and voltage differ from their magnitude; identical final profiles have zero interaction.
        self.axes_rows = [dict(case=n, stage='final', depth_mm=j*.0005, Ex_V_cm=-j*.001, Ey_V_cm=0., Ez_V_cm=0., magnitude_V_cm=j*.001, V=10+j*.001, alpha=.5, pointbits=1, netdensity_cm3=-2.) for n in li.AXES_CASES for j in range(2001)]
        calc = li.axes_comparison(self.axes_rows[:2001], self.axes_rows[:2001])
        normref = 'g22_from50: pointwise max(1 V/cm, norm(E22))'
        g['comparisons'] = [dict(reference=a, candidate=b, accepted_inputs=True, accepted_endpoints=True, accepted_reference=True, normalization_reference=normref, signed_radial_difference_V_cm=[0.]*2001, **copy.deepcopy(calc)) for a, b in li.AXES_PAIRS]
        g['same_grid'] = dict(accepted_inputs=True, coefficients_identical=True, maxV=1e-4, alphavoltage=0., alphavoltage_update_only=0., whole_grid_vector_difference_V_cm=0., classification_changes=0, inconclusive=False, profilecomparison=copy.deepcopy(calc), passed=False, maxinitVdifference=1.)
        g['factorialsummary'] = dict(depth_mm=[j*.0005 for j in range(2001)], signed_radial_profile_V_cm=[0.]*2001, maxnorm_V_cm=0., normalized_interaction=0., normalization_reference=normref, initialization_test_passed=False, signed_local_source_interaction_cm3=[0.]*2001, max_local_source_interaction_cm3=0., accepted_inputs=True)
        return g

    def write_axes(self, g):
        for public, original in li.AXES_FILES.items():
            fields = li.HEADERS[public].split(',')
            rows = self.axes_rows if original == 'profiles.csv' else g['comparisons']
            with (self.axes / original).open('w', newline='') as stream:
                writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
                writer.writerows({k: str(r[k]).lower() if type(r[k]) is bool else 'nothing' if r[k] is None else r[k] for k in fields} for r in rows)
        g['artifacts'] = {n: li.common.sha256(self.axes / n) for n in li.AXES_FILES.values()}
        (self.axes / 'report.json').write_text(json.dumps(g), encoding='utf-8')

    def test_axes_completed_diagnostics_with_failed_agreement(self):
        g = self.axes_fixture(); self.write_axes(g); self.write_fixture()
        output = self.source.parent / 'axes-view'
        previous = li.export(self.source, self.source.parent / 'without-axes', grid_input=self.source.parent / 'grid')
        data = li.export(self.source, output, grid_input=self.source.parent / 'grid', axes_input=self.axes)
        self.assertEqual({k: v for k, v in data.items() if k != 'axis_attribution'}, previous)
        self.assertFalse(data['axis_attribution']['same_grid']['passed'])
        self.assertEqual(data['axis_attribution']['status'], 'completed_attribution_diagnostics')
        self.assertEqual(set(p.name for p in output.iterdir()), {'lithium.html', 'summary.json', *li.FILES[1:], *li.GRID_FILES, *li.AXES_FILES})
        page = (output / 'lithium.html').read_text(encoding='utf-8')
        for token in ('computed profiles', '15.1-percentage-point', 'not new gamma', 'not experimental', 'Actual r/phi/z', 'conditional', '0.0001', 'axes-profiles.csv', 'axes-comparisons.csv', 'class="scroll"'):
            self.assertIn(token, page)
        for token in ('<script', 'cdn', self.root.as_posix(), 'signed_radial_profile_V_cm'):
            self.assertNotIn(token, page)
        self.assertLess(page.index('Initialization and radial/axial attribution'), page.index('Transition grid audit'))
        for name in li.FILES[1:]: self.assertEqual((output / name).read_bytes(), (self.source / name).read_bytes())
        li.validate_bundle(output)
        for public, original in li.AXES_FILES.items():
            self.assertEqual((output / public).read_bytes(), (self.axes / original).read_bytes())
            saved = (output / public).read_bytes(); (output / public).write_bytes(saved + b'changed')
            with self.assertRaises(ValueError): li.validate_bundle(output)
            (output / public).write_bytes(saved)
        data['axis_attribution']['reporter_test_sha256'] = '0'*64
        (output / 'summary.json').write_text(li.common.public_json_text(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'tests changed'): li.validate_bundle(output)

    def test_axes_refuses_forged_claims_and_sources(self):
        original = self.axes_fixture()
        mutations = [lambda g: g.update(status='running'), lambda g: g.update(status='invalid_source_or_runtime'), lambda g: g.update(runtime_seconds=-1), lambda g: g.update(runtime_seconds=0),
            lambda g: g.update(final_sources_unchanged=False), lambda g: g['cases'].pop(), lambda g: g['cases'][0]['nativeitem'].update(E_accepted=False),
            lambda g: g['cases'][0]['nativeitem'].update(E_geometric_contacts=[]), lambda g: g['cases'][0]['nativeitem']['E_checks'][-2]['poisson'].update(max=1e-4),
            lambda g: g['cases'][0]['nativeitem']['E_checks'][-1].update(consecutive_passes=1), lambda g: g['cases'][0].update(elapsed_seconds=901),
            lambda g: g['held_settings'].update(fresh_sweeps=40001), lambda g: g['same_grid'].update(passed=True), lambda g: g['same_grid'].update(coefficients_identical=False),
            lambda g: g['cases'][3]['initial_identity'].update(q_eff_imp='0'*64), lambda g: g['cases'][0]['nativeitem']['E_final_native_hashes'].pop('q_eff_imp'),
            lambda g: g['cases'][0]['final_profile']['target_spacings_um'].__setitem__(0, 25),
            lambda g: g['same_grid']['profilecomparison'].update(normalized_E=.1), lambda g: g['comparisons'][0].update(normalized_E=.1),
            lambda g: g['comparisons'][0].update(onset_bracket_shifts_mm=[[1, 1], [1, 1]]), lambda g: g['factorialsummary']['signed_radial_profile_V_cm'].__setitem__(1, 1),
            lambda g: g['factorialsummary'].update(maxnorm_V_cm=1), lambda g: g['provenance']['sources'].update({'test_transition_axes.jl': '0'*64}),
            lambda g: g['provenance']['Tprovenance']['native_sources'].update({'Native.jl': '0'*64}),
            lambda g: g['provenance']['Tprovenance']['native_sources'].update({'Grids/fixture.jl': '0'*64}),
            lambda g: g['provenance']['Tprovenance'].update(native_tree_sha256='0'*64),
            lambda g: g['comparisons'][0]['signed_radial_difference_V_cm'].__setitem__(1, 1), lambda g: g['factorialsummary'].update(normalized_interaction=1),
            lambda g: g['cases'][0].update(failure='C:/Users/private/file')]
        for mutate in mutations:
            g = copy.deepcopy(original); mutate(g); self.write_axes(g)
            with self.subTest(mutate=mutate), self.assertRaises((ValueError, KeyError)): li.load_axes(self.axes)
        g = copy.deepcopy(original); self.write_axes(g)
        path = self.axes / 'profiles.csv'; path.write_bytes(path.read_bytes().replace(b'Ex_V_cm', b'Wrong_E'))
        g['artifacts']['profiles.csv'] = li.common.sha256(path); (self.axes / 'report.json').write_text(json.dumps(g))
        with self.assertRaisesRegex(ValueError, 'CSV schema'): li.load_axes(self.axes)
        for key, value in (('magnitude_V_cm', 9), ('depth_mm', .7), ('Ex_V_cm', 4)):
            saved = self.axes_rows[3][key]; self.axes_rows[3][key] = value; self.write_axes(original)
            with self.assertRaises(ValueError): li.load_axes(self.axes)
            self.axes_rows[3][key] = saved
        self.write_axes(original); path.write_bytes(path.read_bytes()+b'changed')
        with self.assertRaises(ValueError): li.load_axes(self.axes)
        self.write_axes(original); (self.root / 'simulation/test_transition_axes.jl').write_text('producer test changed')
        with self.assertRaises(ValueError): li.load_axes(self.axes)

    def test_axes_partial_baseline_without_success_data(self):
        g = self.axes_fixture(); g.update(status='partial_cases', baseline_accepted=False, comparisons=[], factorialsummary=None, crosses_blocked_reason='Baseline budget failed')
        g['cases'] = g['cases'][:2]; self.axes_rows = []
        g['same_grid'] = dict(accepted_inputs=False, coefficients_identical=False, maxV=None, alphavoltage=None, profilecomparison=None, passed=False, inconclusive=True)
        for c in g['cases']:
            c.update(status='budget_failed', profile=None, failure='elapsed limit exceeded'); c.pop('final_profile'); c['nativeitem'] = dict(case=c['case'])
        self.write_axes(g); self.write_fixture()
        data = li.export(self.source, self.source.parent / 'partial-axes', axes_input=self.axes)
        self.assertEqual(data['axis_attribution']['status'], 'partial_cases')
        for change in (dict(passed=True), dict(maxV=0.)):
            saved = copy.deepcopy(g['same_grid']); g['same_grid'].update(change); self.write_axes(g)
            with self.assertRaises(ValueError): li.load_axes(self.axes)
            g['same_grid'] = saved

    def test_axes_partial_cross_budget_and_missing_profile(self):
        g = self.axes_fixture(); g.update(status='partial_cases', runtime_seconds=907.)
        c = g['cases'][3]; c.update(status='budget_failed', elapsed_seconds=901., within_cooperative_time_budget=False, budget_reason='Postprocessing exceeded cooperative case budget')
        g['same_grid'].update(accepted_inputs=False, inconclusive=True)
        self.write_axes(g); li.load_axes(self.axes)
        c.pop('final_profile'); c.update(profile=None, failure='elapsed limit exceeded'); c['nativeitem'] = dict(case=c['case'])
        self.axes_rows = [r for r in self.axes_rows if r['case'] != c['case']]
        g['same_grid'] = dict(accepted_inputs=False, coefficients_identical=False, maxV=None, alphavoltage=None, profilecomparison=None, passed=False, inconclusive=True)
        self.write_axes(g); li.load_axes(self.axes)
        g['same_grid']['passed'] = True; self.write_axes(g)
        with self.assertRaises(ValueError): li.load_axes(self.axes)

    def test_axes_partial_normalizer_invalidates_all_effect_gates(self):
        g = self.axes_fixture(); g.update(status='partial_cases', runtime_seconds=907.)
        c = g['cases'][2]; c.update(status='budget_failed', elapsed_seconds=901., within_cooperative_time_budget=False, budget_reason='Postprocessing exceeded cooperative case budget')
        g['same_grid'].update(accepted_inputs=False, inconclusive=True); g['factorialsummary']['accepted_inputs'] = False
        for d in g['comparisons']: d.update(accepted_inputs=False, accepted_reference=False, accepted_endpoints=d['candidate'] != 'g22_from50', passed=False)
        self.write_axes(g); li.load_axes(self.axes)
        g['comparisons'][0].update(accepted_inputs=True, passed=True); self.write_axes(g)
        with self.assertRaises(ValueError): li.load_axes(self.axes)
        c.pop('final_profile'); c.update(profile=None, failure='elapsed limit exceeded'); c['nativeitem'] = dict(case=c['case'])
        self.axes_rows = [r for r in self.axes_rows if r['case'] != c['case']]
        g.update(comparisons=[], factorialsummary=None, unavailable_comparisons=[dict(reference=a, candidate=b, reason='Missing endpoint or E22 normalization profile') for a, b in li.AXES_PAIRS])
        g['same_grid'] = dict(accepted_inputs=False, coefficients_identical=False, maxV=None, alphavoltage=None, profilecomparison=None, passed=False, inconclusive=True)
        self.write_axes(g); li.load_axes(self.axes)

    def test_axes_common_normalization_and_input_race(self):
        a = [dict(depth_mm=0, Ex_V_cm=1., Ey_V_cm=0., Ez_V_cm=0., magnitude_V_cm=1., alpha=1., netdensity_cm3=0.)]
        b = [dict(a[0], Ex_V_cm=3., magnitude_V_cm=3.)]; reference = [dict(a[0], Ex_V_cm=6., magnitude_V_cm=6.)]
        self.assertAlmostEqual(li.axes_comparison(a, b, reference)['normalized_E'], 1/3)
        g = self.axes_fixture(); self.write_axes(g); self.write_fixture()
        render = li.render
        def change_input(data):
            page = render(data); path = self.axes / 'report.json'; path.write_bytes(path.read_bytes()+b' '); return page
        with patch.object(li, 'render', change_input), self.assertRaisesRegex(ValueError, 'axes input changed'):
            li.export(self.source, self.source.parent / 'raced-view', axes_input=self.axes)
        self.assertFalse((self.source.parent / 'raced-view').exists())

    def test_optional_transition_partial_and_guards(self):
        grid, g = self.grid_fixture()
        write = lambda: (grid / 'report.json').write_text(json.dumps(g), encoding='utf-8')
        write()
        self.write_fixture()
        output = self.source.parent / 'transition'
        data = li.export(self.source, output, grid_input=grid)
        self.assertEqual(len(list(output.iterdir())), 7)
        self.assertEqual(data['schema_version'], 1)
        page = (output / 'lithium.html').read_text(encoding='utf-8')
        for token in ('budget_failed', 'Nested results absent', '86.607', 'native numerical checks', 'Grid sensitivity remains unresolved'):
            self.assertIn(token, page)
        for token in ('<script', 'src="http', self.root.as_posix(), 'W did not mutate E'):
            self.assertNotIn(token, page)
        self.assertIn('ticks_m_rad_m_summary', data['transition_grid']['cases'][0]['E_grid'])
        for public, original in li.GRID_FILES.items():
            self.assertIn(f'href="{public}"', page)
            self.assertEqual((output / public).read_bytes(), (grid / original).read_bytes())
            saved = (output / public).read_bytes()
            (output / public).write_bytes(saved + b'changed')
            with self.assertRaises(ValueError): li.validate_bundle(output)
            (output / public).write_bytes(saved)
        original = copy.deepcopy(g)
        for mutate in (lambda: g['artifacts'].update({'profiles.csv': '0'*64}), lambda: g.update(runtime_seconds=float('nan')),
                       lambda: g.update(status='bounded_numerical_convergence', nested_converged=True, baseline_accepted=True),
                       lambda: g['held_settings'].update(profile_relative_gate=.1), lambda: g['cases'][0]['initial']['samples'][0].update(E_V_cm=9),
                       lambda: g['provenance']['native_sources'].update({'Native.jl': '0'*64}), lambda: g.update(status='blocked'),
                       lambda: g['cases'][0].update(failure='C:/Users/private/file'), lambda: g['cases'][0].pop('initial')):
            g = copy.deepcopy(original)
            mutate(); write()
            with self.assertRaises((ValueError, KeyError)): li.load_transition(grid)
        g = copy.deepcopy(original); write()
        li.validate_bundle(output)
        g['cases'][0].update(status='accepted_fixed_grid', E_accepted=True, W_accepted=True)
        write()
        with self.assertRaisesRegex(ValueError, 'false case acceptance'): li.load_transition(grid)
        g = copy.deepcopy(original); write()
        (output / 'unlisted.csv').write_text('unlisted')
        with self.assertRaisesRegex(ValueError, 'unexpected Li bundle files'): li.validate_bundle(output)
        (output / 'unlisted.csv').unlink()
        data['transition_grid']['reporter_test_sha256'] = '0'*64
        (output / 'summary.json').write_text(li.common.public_json_text(data), encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'tests changed'): li.validate_bundle(output)
        (self.root / 'simulation/diagnose_transition_grid.jl').write_text('changed producer')
        with self.assertRaises((ValueError, IndexError)): li.load_transition(grid)


if __name__ == '__main__':
    unittest.main()
