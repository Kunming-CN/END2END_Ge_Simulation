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


if __name__ == '__main__':
    unittest.main()
