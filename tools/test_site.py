"""Fast publication guard tests; no scientific environment or network required."""
import json
import hashlib
import io
import os
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_site import MANIFEST, local_target, validate
import export_models as models

class PublicationTests(unittest.TestCase):
    def test_pixel_depth_figure_shows_abstentions_and_paired_denominators(self):
        import gegi_digital_display as exhibit
        isolated = dict(bounds_mm=[-5, 5], reference_energy_keV=500, intended=2, estimated=1,
                        injected_and_apparent_depth_mm=[[-3, -2.9], [4, None]],
                        paired_cfd_rms_mm=.1, paired_midplane_rms_mm=3.)
        near = dict(mixtures=24, both_depths_available=12, intended_sites=48, depth_estimates=32,
                    paired_sites=32, paired_rms_mm=.660, isolated_rms_mm=.087)
        far = dict(near, depth_estimates=36, paired_sites=36, paired_rms_mm=.074, isolated_rms_mm=.074)
        methods = {name: dict(axis_error_deg=dict(rms=angle), depth_errors_mm=dict(rms=depth))
                   for name, angle, depth in zip(exhibit.JOINT_DEPTH_METHODS, (24.27, 12.31, 12.62),
                                                 (3.06, 1.06, .92), strict=True)}
        cases = [dict(source=source, order=order, waveform_residual_deg=dict(center=center, lateral=lateral),
                      transport_vertices_residual_deg=transport) for source, order, center, lateral, transport in (
                      ('cs137-left', 'true', -20.45, -11.06, -10.60), ('cs137-left', 'reverse', 7.24, -4.74, -4.04),
                      ('co60-right', 'true', -4.27, None, .59), ('co60-right', 'reverse', 58.52, None, 50.72))]
        holdout = {name: dict(axis_error_deg=dict(rms=angle), xy_error_mm=dict(rms=xy))
                   for name, angle, xy in [('center', 18.77, 1.75), ('lateral', 10.81, 1.31)]}
        cones = dict(two_strip_triggers=76, in_line_windows=18, with_conditional_geometry=7, cases=cases,
                     cs_holdout=dict(trials=8, sites=16, metrics=holdout),
                     cs_true_order=dict(photon_path_angle_deg=139.76, outgoing_keV=193.45,
                                        stationary_prediction_outgoing_keV=201.52, geant4_reference='https://github.com/Geant4/geant4'))
        public = dict(isolated=isolated, paired=dict(near=near, disjoint=far),
                      portable=dict(pixel_curve_statuses=dict(available=216, insufficient_center_knots=40),
                                    off_center_pixels=16),
                      joint=dict(matched_occurrences=41, original_groups=27, site_observations=82, methods=methods),
                      cone_references=cones,
                      acquisition=dict(duration_s=.25, single_pixel_statuses=dict(estimated=360, unavailable=124),
                                       assignments_by_depth_count={'2': 34}, energy_compatible_assignments=58))
        panel = exhibit.pixel_depth_section(public)
        self.assertEqual(panel.count('<circle '), 1)
        self.assertIn('show 1 unavailable estimates at their injected depths', panel)
        self.assertIn('viewBox="0 0 381 390"', panel)
        self.assertIn('>12/24</td><td>32/48</td><td>32</td><td>0.660 mm', panel)
        self.assertIn('>12/24</td><td>36/48</td><td>36</td><td>0.074 mm', panel)
        self.assertIn('360/484', panel)
        self.assertIn('34/58', panel)
        self.assertIn('41 matched occurrences from 27 original simulated groups', panel)
        self.assertIn('12.62° with a joint ADC-waveform fit', panel)
        self.assertIn('Cs-137, true order</th><td>−20.45°</td><td>−11.06°</td><td>−10.60°', panel)
        self.assertIn('Cs-137, reverse order</th><td>+7.24°</td><td>−4.74°</td><td>−4.04°', panel)
        self.assertIn('Co-60, true order</th><td>−4.27°</td><td>Center fit only</td><td>+0.59°', panel)
        self.assertIn('Co-60, reverse order</th><td>+58.52°</td><td>Center fit only</td><td>+50.72°', panel)
        self.assertIn('8 held-out two-deposit mixtures', panel)
        self.assertIn('href="gegi-digital/pixel-depth.json"', panel)

    def test_measured_plane_distinguishes_trigger_denominators_and_hypotheses(self):
        import gegi_digital_display as exhibit

        labels = ['661.657_keV', '1173.23_keV', '1332.49_keV']
        def exposure(seconds, milliseconds, qualified, groups):
            layers = {label: dict(triggers=total, triggers_with_geometry=projected, hypotheses=hypotheses,
                                  unresolved_mass=total-projected,
                                  peaks=[dict(position_mm=[-42., 2., 40.], on_image_edge=label in ('all', labels[1]))])
                      for label, (total, projected, hypotheses) in zip(['all', *labels], groups, strict=True)}
            return dict(selection=dict(clock_live_time_ns=seconds*1e9, qualified_adc_live_time_ns=milliseconds*1e6,
                                       qualified_triggers=qualified, two_strip_triggers=groups[0][0]), layers=layers)

        views = dict(first_half=exposure(.5, 453.48338, 2031, [(184, 145, 221), (37, 29, 57), (19, 11, 19), (19, 8, 12)]),
                     second_half=exposure(.5, 452.63636, 1874, [(140, 109, 150), (30, 20, 36), (15, 12, 16), (5, 5, 10)]),
                     full=exposure(1., 906.11974, 3905, [(324, 254, 371), (67, 49, 93), (34, 23, 35), (24, 13, 22)]))
        data = dict(grid=dict(step_mm=4., extent_mm=120., assumed_z_mm=40.), image_size_px=[1890, 1845],
                    angular_nuisance_sigma_deg=5., windows=labels, views=views,
                    split_peak_separation_mm=dict(zip(labels, [190.5, 217.3, 121.5])))
        panel = exhibit.measured_plane_section(data)
        self.assertIn('src="gegi-digital/measured-compton-planes.png"', panel)
        self.assertIn('z = 40 mm with X and Y spanning ±120 mm', panel)
        self.assertIn('4 × 4 mm cell', panel)
        self.assertIn('First half · 0.5 s</th><td>453.483 ms</td><td>145/184 triggers<br>221 hypotheses', panel)
        self.assertIn('Second half · 0.5 s</th><td>452.636 ms</td><td>109/140 triggers<br>150 hypotheses', panel)
        self.assertIn('Pooled · 1 s</th><td>906.120 ms</td><td>254/324 triggers<br>371 hypotheses', panel)
        self.assertIn('<td>49/67 triggers<br>93 hypotheses</td>', panel)
        self.assertIn('1173.23 keV and all energies fall on the display boundary.', panel)
        self.assertIn('pooled map leaves 70 units unresolved', panel)

    def test_gegi_replacement_allows_history_only_for_predecessor(self):
        import build_site as builder
        project=self.site/'gegi-replacement';docs=project/'docs';stage=project/'.local/site-build'
        docs.mkdir(parents=True);(docs/'index.html').write_text('<html><body>saved</body></html>')
        (docs/MANIFEST).write_text('{}')
        def gate(folder,**kwargs):
            return {'build_id':'old' if folder==docs else 'new','files':[]}
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), \
             patch.object(builder,'validate',side_effect=gate) as checked, \
             patch('gegi_campaign_publication.install_bundle') as install, redirect_stdout(io.StringIO()):
            builder.build(gegi_campaign_bundle=project/'candidate')
        install.assert_called_once_with(project/'candidate',stage)
        self.assertEqual(checked.call_args_list,[unittest.mock.call(docs,allow_historical_gegi_sources=True),
            unittest.mock.call(stage,require_manifest=False,require_models=True),unittest.mock.call(stage)])

    def test_restructure_reuses_checked_input_and_keeps_both_candidate_checks(self):
        import build_site as builder
        for has_previous in (False,True):
            with self.subTest(previous=has_previous):
                project=self.site/('checked-'+str(has_previous));docs=project/'docs';stage=project/'.local/site-build'
                docs.mkdir(parents=True);(docs/'index.html').write_text('<html><body>saved</body></html>')
                (docs/MANIFEST).write_text('{}')
                if has_previous:
                    previous=project/'.local/site-previous';previous.mkdir(parents=True);(previous/'index.html').write_text('older')
                def gate(folder,**kwargs):
                    return {'build_id':'old' if folder==docs else 'new','files':[]}
                with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage),patch.object(builder,'validate',side_effect=gate) as checked,redirect_stdout(io.StringIO()):
                    builder.build(restructure=True)
                self.assertEqual(checked.call_args_list,[unittest.mock.call(docs),
                    unittest.mock.call(stage,require_manifest=False,require_models=True),unittest.mock.call(stage)])

    def test_staged_recovery_requires_validated_snapshot_and_stage(self):
        import build_site as builder
        project=self.site/'recovery'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n')
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(builder,'validate') as gate:
            with self.assertRaisesRegex(ValueError,'real generated stage'):builder.finish_staged()
            stage.mkdir(parents=True); (stage/'index.html').write_bytes(b'generated\n')
            backup=project/'.local/site-previous'; backup.mkdir()
            with self.assertRaisesRegex(ValueError,'pending atomic swap'):builder.finish_staged()
            backup.rmdir()
            before={p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()}
            def reject_stage(folder,**kwargs):
                if folder==docs:return {'build_id':'old'}
                self.assertEqual(kwargs,{'require_manifest':False,'require_models':True})
                raise ValueError('invalid source-bound staged payload')
            gate.side_effect=reject_stage
            with self.assertRaisesRegex(ValueError,'invalid source-bound'):builder.finish_staged()
            self.assertEqual(before,{p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()})

    def test_staged_recovery_shares_atomic_install_without_generation(self):
        import build_site as builder
        project=self.site/'recovery-success'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n'); (docs/'index.html').write_bytes(b'old\n')
        stage.mkdir(parents=True); (stage/'index.html').write_bytes(b'new\n')
        def checked(folder,**kwargs):return {'build_id':'old' if folder==docs else 'new','files':[]}
        printed=io.StringIO()
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(builder,'validate',side_effect=checked) as gate, patch.object(builder,'build',side_effect=AssertionError('must not regenerate')), redirect_stdout(printed):
            summary=builder.finish_staged()
            self.assertEqual(gate.call_args_list,[unittest.mock.call(docs),unittest.mock.call(stage,require_manifest=False,require_models=True),unittest.mock.call(stage)])
        self.assertEqual(summary,{'build_id':'new'})
        self.assertEqual(json.loads(printed.getvalue().split('\n',1)[1]),summary)
        self.assertEqual((docs/'index.html').read_bytes(),b'new\n')
        self.assertFalse(stage.exists()); self.assertFalse((project/'.local/site-previous').exists())

    def test_staged_recovery_is_exclusive_with_generation_mode(self):
        script=Path(__file__).with_name('build_site.py')
        result=subprocess.run([sys.executable,'-B',str(script),'--finish-staged','--restructure'],capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('Select one publication mode',result.stderr)

    def test_staged_recovery_refuses_junctions_and_linked_ancestors(self):
        import build_site as builder
        project=self.site/'recovery-links'; docs=project/'docs'; stage=project/'.local/site-build'
        docs.mkdir(parents=True); (docs/MANIFEST).write_bytes(b'{}\n'); stage.mkdir(parents=True)
        before={p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()}
        for linked in (stage, stage.parent, docs, project):
            with self.subTest(linked=linked), patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=stage), patch.object(Path,'is_junction',lambda path:path==linked,create=True), patch.object(builder,'validate') as gate, patch.object(builder,'install_snapshot') as installer:
                with self.assertRaisesRegex(ValueError,'real generated stage'):builder.finish_staged()
                gate.assert_not_called(); installer.assert_not_called()
        self.assertEqual(before,{p.relative_to(project):p.read_bytes() for p in project.rglob('*') if p.is_file()})

    def test_hash_bound_ring_text_keeps_exact_line_endings(self):
        import build_site as builder
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / '.local') as temporary:
            folder = Path(temporary)
            ring = folder / 'examples/cs137-10k-rings/KMRC01_candidate/response/summary.html'
            ring.parent.mkdir(parents=True)
            body = b'<html>saved byte-exact result</html>\r\n'
            ring.write_bytes(body)
            builder.normalize_text_outputs(folder)
            self.assertEqual(ring.read_bytes(), body)

    def test_hash_bound_gegi_bundles_keep_exact_line_endings(self):
        import build_site as builder
        for relative in ('assemblies/gegi/event-data.json', 'results/gegi-campaign/summary.json'):
            with self.subTest(relative=relative):
                target=self.site/relative; target.parent.mkdir(parents=True,exist_ok=True)
                body=b'{"saved":true}\r\n'; target.write_bytes(body)
                ordinary=self.site/'navigation.json'; ordinary.write_bytes(body)
                builder.normalize_text_outputs(self.site)
                self.assertEqual(target.read_bytes(),body)
                self.assertEqual(ordinary.read_bytes(),body.replace(b'\r\n',b'\n'))

    def setUp(self):
        local = Path(__file__).resolve().parents[1] / '.local'
        local.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='site-test-', dir=local)
        self.site = Path(self.directory.name)
        self.addCleanup(self.directory.cleanup)
        (self.site / 'index.html').write_text('<a href="signal.csv">Data</a>', encoding='utf-8')
        (self.site / 'signal.csv').write_text('time_ns,Q\n0,0\n1,1\n', encoding='utf-8')

    def seal(self):
        report = validate(self.site, require_manifest=False)
        (self.site / MANIFEST).write_text(json.dumps(report), encoding='utf-8')
        return report

    def test_host_size_limits_refuse_before_publication_without_large_fixture(self):
        import check_site as checker
        # Lower only the operational limits; real file sizes and hashes stay real.
        with patch.object(checker, 'MAX_PUBLIC_FILE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'publication size limit'):
                validate(self.site, require_manifest=False)

    def test_host_size_budget_includes_existing_and_generated_manifest(self):
        import check_site as checker
        report=self.seal(); payload=report['total_bytes']; manifest=self.site/MANIFEST
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+manifest.stat().st_size-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site)
        generated=len((json.dumps(report,indent=2)+'\n').encode('utf-8'))
        self.assertLess(manifest.stat().st_size,generated)
        # Re-sealing replaces a valid compact manifest with the generated pretty
        # serialization; its old on-disk size must not underestimate that write.
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site,require_manifest=False)
        manifest.unlink()
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated-1):
            with self.assertRaisesRegex(ValueError,'including the site manifest'):validate(self.site,require_manifest=False)
        with patch.object(checker,'MAX_PUBLIC_SITE_BYTES',payload+generated):
            self.assertEqual(validate(self.site,require_manifest=False),report)
        with patch.object(checker, 'MAX_PUBLIC_SITE_BYTES', 1):
            with self.assertRaisesRegex(ValueError, 'publication size limit'):
                validate(self.site, require_manifest=False)

    def test_gamma_explicit_mode_copies_checked_bytes_without_export(self):
        import build_site as builder
        import gamma_showcase
        project = self.site / 'gamma-mode-fixture'; docs = project / 'docs'
        docs.mkdir(parents=True); (docs / 'index.html').write_bytes(b'old saved snapshot\n')
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        original = {p.name: p.read_bytes() for p in docs.iterdir()}
        bundle = project / 'synthetic-bundle'; bundle.mkdir()
        for name in (*gamma_showcase.FILES, 'publication.json'):
            (bundle / name).write_bytes(b'synthetic fixture\r\n')
        stage = project / '.local' / 'site-build'
        with patch.multiple(builder, DESTINATION=docs, OUT=stage), \
             patch.object(gamma_showcase, 'ROOT', project), \
             patch('gamma_showcase.validate_bundle') as checked, \
             patch('gamma_showcase.export_saved', side_effect=AssertionError('Export forbidden')):
            builder.build_gamma_export(bundle)
        self.assertEqual(checked.call_count, 2)
        self.assertEqual(original, {p.name: p.read_bytes() for p in docs.iterdir()})
        for name in (*gamma_showcase.FILES, 'publication.json'):
            self.assertEqual((stage / 'examples/gamma-native' / name).read_bytes(), (bundle / name).read_bytes())
        builder.normalize_text_outputs(stage)
        self.assertEqual((stage / 'examples/gamma-native/gamma.html').read_bytes(), b'synthetic fixture\r\n')

    def test_explicit_gamma_mode_reconciles_only_staged_saved_files(self):
        import build_site as builder
        import gamma_showcase
        project = self.site / 'gamma-update-fixture'; docs = project / 'docs'
        old_gamma = docs / 'examples/gamma-native'; old_gamma.mkdir(parents=True)
        (docs / 'index.html').write_bytes(b'old saved snapshot\n')
        for name in (*gamma_showcase.FILES, 'publication.json'): (old_gamma / name).write_bytes(b'old fixture\n')
        bundle = project / 'new-bundle'; bundle.mkdir()
        for name in (*gamma_showcase.FILES, 'publication.json'): (bundle / name).write_bytes(b'new fixture\n')
        stage = project / '.local/site-build'
        before = {p.relative_to(docs).as_posix(): p.read_bytes() for p in docs.rglob('*') if p.is_file()}
        (docs / MANIFEST).write_text('{}')
        with patch.multiple(builder, DESTINATION=docs, OUT=stage), \
             patch.object(builder, 'validate'), patch.object(gamma_showcase, 'ROOT', project), \
             patch('gamma_showcase.validate_bundle') as checked, \
             patch('gamma_showcase.export_saved', side_effect=AssertionError('Export forbidden')):
            builder.build_gamma_export(bundle)
        self.assertEqual(checked.call_count, 3)
        for name, raw in before.items(): self.assertEqual((docs / name).read_bytes(), raw)
        self.assertEqual((stage / 'index.html').read_bytes(), before['index.html'])
        for name in (*gamma_showcase.FILES, 'publication.json'):
            self.assertEqual((stage / 'examples/gamma-native' / name).read_bytes(), (bundle / name).read_bytes())

    def test_site_validator_refuses_partial_gamma_bundle(self):
        (self.site / 'examples/gamma-native').mkdir(parents=True)
        with self.assertRaisesRegex(ValueError, 'public inventory'):
            validate(self.site, require_manifest=False)

    def test_normal_restructure_preserves_saved_gamma_bundle_without_export(self):
        import build_site as builder
        import gamma_showcase
        project=self.site/'gamma-preservation-fixture';docs=project/'docs'
        gamma=docs/'examples/gamma-native';gamma.mkdir(parents=True)
        (docs/'index.html').write_bytes(b'<a href="examples/gamma-native/gamma.html">Saved example</a>\n')
        for name in (*gamma_showcase.FILES,'publication.json'):
            (gamma/name).write_bytes(b'{}\n' if name.endswith('.json') else b'synthetic saved bytes\r\n')
        with patch('gamma_showcase.validate_bundle'):
            sealed=validate(docs,require_manifest=False)
        (docs/MANIFEST).write_text(json.dumps(sealed))
        before={p.relative_to(docs).as_posix():(p.read_bytes(),p.stat().st_mtime_ns) for p in docs.rglob('*') if p.is_file()}
        def fixture_validate(folder,**kwargs):
            return validate(folder,require_manifest=kwargs.get('require_manifest',True))
        with patch.multiple(builder,ROOT=project,DESTINATION=docs,OUT=project/'.local/site-build'), \
             patch.object(builder,'validate',fixture_validate),patch('viewer_navigation.assemble'), \
             patch('gamma_showcase.validate_bundle'), \
             patch('gamma_showcase.export_saved',side_effect=AssertionError('Export forbidden')), \
             patch.object(builder,'build_export',side_effect=AssertionError('Legacy export forbidden')):
            builder.build(restructure=True)
        after={p.relative_to(docs).as_posix():(p.read_bytes(),p.stat().st_mtime_ns) for p in docs.rglob('*') if p.is_file()}
        self.assertEqual(before,after)

    def test_native_example_export_guard(self):
        import hashlib
        import build_site as builder
        directory = self.site / '.local' / 'native-li-example'
        directory.mkdir(parents=True)
        source = self.site / 'simulation'; source.mkdir()
        names = ('run.jl', 'replay.jl', 'readout.jl', 'native_li_example.jl', 'test_native_li_example.jl', 'readout_demo.json')
        hashes = {}
        for name in names:
            (source / name).write_bytes(b'fixture')
            hashes[name] = hashlib.sha256(b'fixture').hexdigest()
        artifacts = {}
        for name in ('comparison.html', 'summary.csv', 'signals.csv'):
            (directory / name).write_bytes(b'fixture')
            artifacts[name] = hashlib.sha256(b'fixture').hexdigest()
        report = dict(status='completed_provisional_native_example', selected_event_ids=[0,2,41,78], source_primary_count=100,
                      unprocessed_event_ids=[i for i in range(100) if i not in (0,2,41,78)], cases=[{}]*14,
                      source_code_sha256=hashes, artifacts=artifacts)
        def save(): (directory / 'report.json').write_text(json.dumps(report))
        save()
        with patch.object(builder, 'ROOT', self.site):
            self.assertEqual(len(builder.native_example_files()[1]), 4)
            (directory / 'summary.csv').write_bytes(b'changed')
            with self.assertRaisesRegex(ValueError, 'output changed'): builder.native_example_files()
            (directory / 'summary.csv').write_bytes(b'fixture')
            report['cases'].pop(); save()
            with self.assertRaisesRegex(ValueError, 'census'): builder.native_example_files()

    def test_reproducible_manifest(self):
        self.assertEqual(self.seal(), validate(self.site))
        self.assertEqual(self.seal(), validate(self.site))

    def test_case_sensitive_links(self):
        (self.site / 'index.html').write_text('<img src="Signal.csv">')
        with self.assertRaisesRegex(ValueError, 'wrong-case'):
            validate(self.site, require_manifest=False)

    def test_changed_or_stale_files(self):
        self.seal()
        (self.site / 'unused.csv').write_text('x\n1\n')
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate(self.site)

    def test_no_private_paths(self):
        (self.site / 'index.html').write_text(r'C:\Users\someone\model.yaml')
        with self.assertRaisesRegex(ValueError, 'Local path'):
            validate(self.site, require_manifest=False)

    def test_raw_cache_is_not_publishable(self):
        (self.site / 'fields.jls').write_bytes(b'not a web resource')
        with self.assertRaisesRegex(ValueError, 'Unapproved'):
            validate(self.site, require_manifest=False)

    def test_jsonl_requires_ring_prefix_and_bundle_validation(self):
        ring=self.site/'examples/cs137-10k-rings/GeRC02/response/scalars.jsonl'
        ring.parent.mkdir(parents=True)
        ring.write_bytes(b'{"signed":-0.0,"unknown":null}\n')
        # Only the file-policy boundary is synthetic here. Full scientific
        # validation has its own real bundle and mutation regression.
        with patch('ring_publication.validate_bundle',return_value={}) as check_ring:
            validate(self.site,require_manifest=False)
            check_ring.assert_called_once_with(self.site/'examples/cs137-10k-rings')
        (self.site/'scalars.jsonl').write_bytes(ring.read_bytes())
        with self.assertRaisesRegex(ValueError,'Unapproved public file'):
            validate(self.site,require_manifest=False)

    def test_gegi_journey_script_requires_bound_bundle_and_exact_route(self):
        bundle=self.site/'results/gegi-campaign';bundle.mkdir(parents=True)
        script=bundle/'gegi_signal_journey.js';script.write_text('/* synthetic file-policy fixture */')
        with self.assertRaisesRegex(ValueError,'complete hash-bound campaign bundle'):
            validate(self.site,require_manifest=False)
        (bundle/'publication.json').write_text('{}')
        with patch('gegi_campaign_publication.validate_bundle',return_value={}) as gate:
            validate(self.site,require_manifest=False)
            gate.assert_called_once_with(bundle)
        (bundle/'unbound.js').write_text('/* not an approved public route */')
        with self.assertRaisesRegex(ValueError,'Unapproved public file'):
            validate(self.site,require_manifest=False)

    def test_url_boundaries(self):
        self.assertEqual(local_target('detectors/A/index.html', '../../index.html'), 'index.html')
        self.assertIsNone(local_target('index.html', 'https://example.org/'))
        for url in ('../secret.csv', '/wrong-root.csv', 'file:///private.csv'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                local_target('index.html', url)


    def test_failed_export_preserves_previous_snapshot(self):
        from unittest.mock import patch
        import build_site
        project = self.site / 'project'
        docs = project / 'docs'
        docs.mkdir(parents=True)
        original = '<p>previous valid snapshot</p>'
        (docs / 'index.html').write_text(original)
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        stage = project / '.local' / 'site-build'
        def bad_export():
            stage.mkdir()
            (stage / 'index.html').write_text('<img src="missing.png">')
        with patch.multiple(build_site, ROOT=project, DESTINATION=docs, OUT=stage), patch.object(build_site, 'build_export', bad_export):
            with self.assertRaisesRegex(ValueError, 'Broken'):
                build_site.build()
        self.assertEqual((docs / 'index.html').read_text(), original)
        self.assertEqual(validate(docs), sealed)

    @unittest.skipUnless(os.name == 'nt', 'Windows read-only directory regression')
    def test_unchanged_export_cleans_readonly_stage_without_rewriting_docs(self):
        import build_site
        project = self.site / 'unchanged-project'
        docs = project / 'docs'
        nested = docs / 'assets' / 'nested'
        nested.mkdir(parents=True)
        (docs / 'index.html').write_text('<a href="assets/nested/data.csv">Data</a>')
        (nested / 'data.csv').write_text('x\n1\n')
        sealed = validate(docs, require_manifest=False)
        (docs / MANIFEST).write_text(json.dumps(sealed))
        before = {p.relative_to(docs).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                  for p in docs.rglob('*') if p.is_file()}
        stage = project / '.local' / 'site-build'
        def identical_export():
            build_site.shutil.copytree(docs, stage)
            (stage / MANIFEST).unlink()
            os.chmod(stage / 'assets' / 'nested', stat.S_IREAD)
        def fixture_validate(folder, **kwargs):
            return validate(folder, require_manifest=kwargs.get('require_manifest', True))
        # Bounded saved-byte fixture omits model/gallery/readers; real publication
        # remains separately checked against the complete preserved snapshot.
        with patch.multiple(build_site, ROOT=project, DESTINATION=docs, OUT=stage), \
             patch.object(build_site, 'build_export', identical_export), \
             patch.object(build_site, 'validate', fixture_validate), \
             patch('viewer_navigation.assemble'):
            try:
                build_site.build()
                self.assertFalse(stage.exists())
            finally:
                if stage.exists():
                    build_site.remove_generated(stage)
        after = {p.relative_to(docs).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                 for p in docs.rglob('*') if p.is_file()}
        self.assertEqual(before, after)
        self.assertEqual(validate(docs), sealed)


class ModelTests(unittest.TestCase):
    def setUp(self):
        local = Path(__file__).resolve().parents[1] / '.local'
        local.mkdir(exist_ok=True)
        self.directory = tempfile.TemporaryDirectory(prefix='model-test-', dir=local)
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)

    def fixture(self, name, data):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return path

    def test_exact_bytes_and_include_closure(self):
        original = b'name: example\r\nconfig:\r\n  include: shared/drift.yaml\r\n'
        source = self.fixture('source/model.yaml', original)
        dependency = b'model: ADLChargeDriftModel\r\n'
        self.fixture('source/shared/drift.yaml', dependency)
        files = {}
        self.assertEqual(models.collect_model(source, source.parent, 'example.yaml', files),
                         ['shared/drift.yaml'])
        destination = self.root / 'output'
        models.write_new_or_identical(destination, files)
        models.write_new_or_identical(destination, files)
        self.assertEqual((destination / 'example.yaml').read_bytes(), original)
        self.assertEqual((destination / 'shared/drift.yaml').read_bytes(), dependency)
        packed = models.archive_bytes(files)
        models.validate_archive(packed, files)
        with zipfile.ZipFile(io.BytesIO(packed)) as archive:
            self.assertEqual(archive.read('example.yaml'), original)

    def test_unsupported_and_unsafe_includes(self):
        cases = ['include: ../escape.yaml', 'include: /absolute.yaml',
                 'include: C:/private.yaml', 'include: shared\\file.yaml',
                 'include: [a.yaml]', 'include: {path: a.yaml}',
                 'include: "a.yaml"', "'include': a.yaml", 'include: |\n  a.yaml',
                 'include:\n  - a.yaml', 'include: !file a.yaml',
                 'include: &ref a.yaml', 'include: *ref',
                 '"in\\u0063lude": a.yaml', '? include\n: a.yaml',
                 'config: {include: a.yaml}', 'include: a.yaml\n  continued',
                 'include: a.yaml\n---\ninclude: b.yaml', 'include: CON.yaml']
        for text in cases:
            with self.subTest(text=text), self.assertRaises(ValueError):
                models.includes(text.encode())

    def test_cycles_conflicts_and_missing_dependencies(self):
        source = self.fixture('source/a.yaml', b'include: b.yaml\n')
        self.fixture('source/b.yaml', b'include: a.yaml\n')
        with self.assertRaisesRegex(ValueError, 'cycle'):
            models.collect_model(source, source.parent, 'a.yaml', {})
        source.write_bytes(b'include: missing.yaml\n')
        with self.assertRaises(FileNotFoundError):
            models.collect_model(source, source.parent, 'a.yaml', {})
        source.write_bytes(b'model: test\n')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.collect_model(source, source.parent, 'a.yaml', {'a.yaml': b'other'})
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.collect_model(source, source.parent, 'a.yaml', {'A.yaml': source.read_bytes()})
        with self.assertRaisesRegex(ValueError, 'approved model root'):
            models.collect_model(source, self.root / 'elsewhere', 'a.yaml', {})

    def test_symlinks_are_rejected(self):
        # Mock the filesystem predicate so this guard runs without Windows
        # symlink privileges. No permissions or developer-mode changes needed.
        source = self.fixture('a.yaml', b'model: test\n')
        with patch.object(Path, 'is_symlink', return_value=True):
            with self.assertRaisesRegex(ValueError, 'Symlink'):
                models.collect_model(source, source.parent, 'a.yaml', {})

    def test_existing_edits_fail_before_writing(self):
        destination = self.root / 'output'
        self.fixture('output/z.yaml', b'user edit')
        with self.assertRaisesRegex(ValueError, 'differs'):
            models.write_new_or_identical(destination, {'a.yaml': b'new', 'z.yaml': b'original'})
        self.assertFalse((destination / 'a.yaml').exists())
        self.assertEqual((destination / 'z.yaml').read_bytes(), b'user edit')

    def test_changed_source_hash(self):
        # A synthetic local catalog exercises import's pre-copy hash guard;
        # tests never need the external GeGI input or ignored original workspace.
        folder = self.root / 'Additional_Simulations/models'
        folder.mkdir(parents=True)
        (folder / 'AK01.yaml').write_bytes(b'name: changed\n')
        items = [{'id': name, 'group': 'thesis', 'model': str(folder / (name + '.yaml')),
                  'model_sha256': sha} for name, sha in models.ORIGINAL_HASHES.items()]
        catalog = self.fixture('catalog.json', models.json_bytes({'detectors': items}))
        with patch.multiple(models, ROOT=self.root, SOURCE_CATALOG=catalog):
            with self.assertRaisesRegex(ValueError, 'Changed original source hash'):
                models.source_snapshot()
            (folder / 'AK01.yaml').write_bytes((models.MODELS / 'AK01.yaml').read_bytes())
            next(item for item in items if item['id'] == 'AK01')['model_sha256'] = '0' * 64
            catalog.write_bytes(models.json_bytes({'detectors': items}))
            with self.assertRaisesRegex(ValueError, 'Changed original source hash'):
                models.source_snapshot()

    def test_archive_paths_and_metadata(self):
        for name in ('../x.yaml', '/x.yaml', 'C:/x.yaml', 'a\\x.yaml',
                     'a/./x.yaml', 'a//x.yaml', 'NUL.yaml', 'a./x.yaml'):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                archive.writestr(name, b'model: test\n')
            # Windows ZipInfo normalizes backslashes when writing. Restore the
            # malicious name in both headers to test the reader's real boundary.
            packed = stream.getvalue().replace(name.replace('\\', '/').encode(), name.encode())
            with self.subTest(name=name), self.assertRaisesRegex(ValueError, 'Unsafe path'):
                models.validate_archive(packed, {name: b'model: test\n'})
        for mode in (stat.S_IFLNK, stat.S_IFDIR):
            stream = io.BytesIO()
            with zipfile.ZipFile(stream, 'w') as archive:
                info = zipfile.ZipInfo('a.yaml', (1980, 1, 1, 0, 0, 0))
                info.external_attr = (mode | 0o777) << 16
                archive.writestr(info, b'target')
            with self.assertRaisesRegex(ValueError, 'Unsafe'):
                models.validate_archive(stream.getvalue(), {'a.yaml': b'target'})
        with self.assertRaisesRegex(ValueError, 'inventory'):
            models.validate_archive(models.archive_bytes({'a.yaml': b'x'}), {'a.yaml': b'x', 'b.yaml': b'y'})
        for data in (b'C:\\Users\\private\\file', b'-----BEGIN PRIVATE KEY-----'):
            with self.assertRaisesRegex(ValueError, 'Private path'):
                models.validate_archive(models.archive_bytes({'a.yaml': data}), {'a.yaml': data})
        hidden = br'{"source": "C:\u005cUsers\u005cprivate"}'
        with self.assertRaisesRegex(ValueError, 'Private path'):
            models.public_text(hidden, 'catalog.json')
        with self.assertRaisesRegex(ValueError, 'Conflicting'):
            models.archive_bytes({'a.yaml': b'x', 'A.yaml': b'x'})

    def test_distribution_archives_reproducible_and_complete(self):
        files = models.read_distribution(models.MODELS)
        downloads = models.download_files(files)
        self.assertEqual(downloads, models.download_files(dict(reversed(list(files.items())))))
        self.assertEqual(len(downloads), 38)  # 20 distribution files + 18 ZIPs
        catalog = json.loads(files['catalog.json'])
        self.assertEqual(sum(bool(d['dependencies']) for d in catalog['detectors']), 9)
        models.validate_archive(downloads['downloads/all-models.zip'], files)
        for detector in catalog['detectors']:
            data = downloads['downloads/' + detector['id'] + '.zip']
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertEqual(set(archive.namelist()),
                                 {detector['model'], *detector['dependencies'], 'catalog.json', 'README.md'})
                self.assertEqual(archive.read(detector['model']), files[detector['model']])
                self.assertEqual(json.loads(archive.read('catalog.json'))['detectors'], [detector])
        changed = dict(files, **{'AK01.yaml': files['AK01.yaml'] + b'\n'})
        with self.assertRaisesRegex(ValueError, 'Changed original hash'):
            models.validate_files(changed)

    def model_site(self):
        from build_site import adapt
        from site_discovery import assemble
        page_html = '<html><head><title>Models</title></head><body><main></main></body></html>'
        files = models.download_files(models.read_distribution(models.MODELS))
        files['index.html'] = adapt(page_html, Path('index.html')).encode()
        files['guide.html'] = b'<html><head><title>Guide</title></head><body><a href="downloads/all-models.zip">All models</a></body></html>'
        files['examples/pipeline.html'] = b'<a href="data.json">Example data</a>'
        files['examples/data.json'] = b'{}'
        files['examples/native-li/comparison.html'] = b'Native demonstration fixture'
        files['lithium/lithium.html'] = b'<a href="../index.html">Library</a>'
        for detector in models.ORIGINAL_HASHES:
            page = f'detectors/{detector}/index.html'
            files[page] = adapt(page_html, Path(page)).encode()
            files[f'detectors/{detector}/technical.html'] = (
                f'<a href="../../models/{detector}.yaml">Original YAML</a>'
                f'<a href="../../downloads/{detector}.zip">Model ZIP</a>').encode()
            if detector != 'GeGI_3D':
                # Bounded fixture for the new full-size illustration link.
                files[f'detectors/{detector}/runs/20260922_suite_v3/01_geometry.png'] = b'\x89PNG\r\n\x1a\n'
        # Existing homepage/GeGI links need only bounded placeholder pages.
        for name in ('strip_explorer.html', 'supplement.html', 'octagon_geometry.png'):
            files['detectors/GeGI_3D/' + name] = b''
        models.write_new_or_identical(self.root, files)
        assemble(self.root)
        return {p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob('*') if p.is_file()}

    def test_bounded_download_site_and_missing_dependencies(self):
        self.model_site()
        report = validate(self.root, require_manifest=False, require_models=True)
        (self.root / MANIFEST).write_bytes(models.json_bytes(report))
        self.assertEqual(validate(self.root), report)
        dependency = self.root / 'models/ADLChargeDriftModel/drift_velocity_config.yaml'
        dependency.unlink()
        with self.assertRaisesRegex(ValueError, 'Missing model downloads'):
            validate(self.root, require_manifest=False)

    def test_site_rejects_changed_download_and_missing_links(self):
        files = self.model_site()
        archive = self.root / 'downloads/AK01.zip'
        archive.write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError, 'differs'):
            validate(self.root, require_manifest=False)
        archive.write_bytes(files['downloads/AK01.zip'])
        (self.root / 'detectors/AK01/technical.html').write_text('<main></main>')
        with self.assertRaisesRegex(ValueError, 'Missing model download links'):
            validate(self.root, require_manifest=False)

    def test_live_check_requests_every_model_and_ring_download(self):
        from check_site import verify_live
        from urllib.parse import unquote, urlsplit
        files = self.model_site()
        report = validate(self.root, require_manifest=False)
        # Synthetic network fixtures exercise complete ring-prefix selection;
        # this test does not claim they are valid saved scientific artifacts.
        for name, data in {
            'examples/cs137-10k-rings/GeRC02/raw/events-000.json.gz': b'gzip-fixture',
            'examples/cs137-10k-rings/KMRC01_candidate/response/ledgers.zip': b'zip-fixture',
            'examples/cs137-10k-rings/packaging-source-manifest.json': b'manifest-fixture',
        }.items():
            files[name] = data
            report['files'].append(dict(path=name, bytes=len(data), sha256=hashlib.sha256(data).hexdigest()))
        files[MANIFEST] = models.json_bytes(report)
        requested = set()

        def fake_open(request, timeout):
            name = unquote(urlsplit(request.full_url).path).removeprefix('/site/')
            requested.add(name)
            return io.BytesIO(files[name])

        # Exercise the normal network path using an in-memory transport, even
        # under ParaView Python without SSL. This is not a live deployment test.
        with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open):
            verify_live('https://example.org/site/', report)
        expected = {name for name in files if name.startswith(('models/', 'downloads/', 'examples/cs137-10k-rings/'))}
        expected.update({'LICENSE', 'sitemap.xml'})
        self.assertTrue(expected <= requested)


class LiveVerificationTests(unittest.TestCase):
    def setUp(self):
        self.path = 'results/saved target.html'
        self.data = b'<main>Original saved bytes</main>'
        self.report = {'build_id': 'live-test', 'files': [dict(path=self.path, bytes=len(self.data),
                      sha256=hashlib.sha256(self.data).hexdigest())]}
        self.files = {self.path: self.data, MANIFEST: json.dumps(self.report).encode()}
        self.requests = []

    def response(self, request):
        from urllib.parse import unquote, urlsplit
        path = unquote(urlsplit(request.full_url).path).removeprefix('/site/')
        self.requests.append(path)
        return path

    def test_live_503_then_success_retries_only_failed_get(self):
        from check_site import verify_live
        from urllib.error import HTTPError
        def fake_open(request, timeout):
            path = self.response(request)
            if path == self.path and self.requests.count(path) == 1:
                raise HTTPError(request.full_url, 503, 'Service Unavailable', {}, io.BytesIO())
            return io.BytesIO(self.files[path])
        with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open), patch('time.sleep') as sleep:
            self.assertEqual(verify_live('https://example.org/site/', self.report), 1)
        self.assertEqual(self.requests.count(MANIFEST), 1)
        self.assertEqual(self.requests.count(self.path), 2)
        sleep.assert_called_once_with(1)

    def test_live_persistent_503_reports_path_and_target_after_three_attempts(self):
        from check_site import verify_live
        from urllib.error import HTTPError
        def fake_open(request, timeout):
            path = self.response(request)
            if path == self.path:
                raise HTTPError(request.full_url, 503, 'Service Unavailable', {}, io.BytesIO())
            return io.BytesIO(self.files[path])
        with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open), patch('time.sleep') as sleep:
            with self.assertRaises(RuntimeError) as caught:
                verify_live('https://example.org/site/', self.report)
        message = str(caught.exception)
        self.assertIn(self.path, message)
        self.assertIn('https://example.org/site/results/saved%20target.html?build=live-test', message)
        self.assertIn('after 3 attempts', message)
        self.assertIsInstance(caught.exception.__cause__, HTTPError)
        self.assertEqual(self.requests.count(self.path), 3)
        self.assertEqual([call.args for call in sleep.call_args_list], [(1,), (2,)])

    def test_live_other_http_errors_are_not_retried(self):
        from check_site import verify_live
        from urllib.error import HTTPError
        for status in (404, 500):
            with self.subTest(status=status):
                self.requests.clear()
                def fake_open(request, timeout):
                    path = self.response(request)
                    if path == self.path:
                        raise HTTPError(request.full_url, status, 'Other HTTP failure', {}, io.BytesIO())
                    return io.BytesIO(self.files[path])
                with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open), patch('time.sleep') as sleep:
                    with self.assertRaises(HTTPError) as caught:
                        verify_live('https://example.org/site/', self.report)
                self.assertEqual(caught.exception.code, status)
                self.assertEqual(self.requests.count(self.path), 1)
                sleep.assert_not_called()

    def test_live_hash_mismatch_is_not_retried(self):
        from check_site import verify_live
        def fake_open(request, timeout):
            path = self.response(request)
            data = bytes(value ^ 1 for value in self.data) if path == self.path else self.files[path]
            return io.BytesIO(data)
        with patch.dict(sys.modules, {'ssl': object()}), patch('urllib.request.urlopen', fake_open), patch('time.sleep') as sleep:
            with self.assertRaisesRegex(ValueError, 'Live content differs'):
                verify_live('https://example.org/site/', self.report)
        self.assertEqual(self.requests.count(self.path), 1)
        sleep.assert_not_called()


if __name__ == '__main__':
    unittest.main(verbosity=2)
