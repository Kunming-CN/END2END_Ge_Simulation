"""Saved-spectrum display regression. No radiation, field or readout computation."""
import copy
import hashlib
import json
import re
import shutil
import os
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
import spectrum_display as D
import spectrum_plot as P
ROOT=Path(__file__).resolve().parents[1]
NODE=os.environ.get('SPECTRUM_NODE') or shutil.which('node')

def toy(counts,edges=None):
    edges=edges or list(range(len(counts)+1))
    return D.specification('test','Synthetic bin fixture',edges,
        [{'label':'Counts','color':'#123456','counts':counts,'total':sum(counts),
          'underflow':0,'overflow':0,'exact_zero':0}],[edges[0],edges[-1]])

def legacy_pipeline_fixture(site):
    """Small synthetic parser fixture; independent of the retired public payload."""
    data={'settings':{'energy_keV':662},'models':[
        {'model_id':model,'events':[{'deposited_energy_keV':0,'reconstructed_energy_keV':None,'accepted':False},
                                   {'deposited_energy_keV':500,'reconstructed_energy_keV':499,'accepted':True}]}
        for model in ('AK02','SAP22')]}
    payload=json.dumps(data)
    page=('<html><body><div style="padding:12px 24px;background:#fff;color:#173047">'
        '<a href="../index.html">GeSignal home</a><nav aria-label="Primary"></nav></div>'
        '<section class="dataset-context" aria-label="Saved dataset"></section>'
        '<a href="../index.html">← Detector library</a><h1>Synthetic legacy pipeline fixture</h1>'
        '<p>Geant4 deposited-energy truth · Accepted peak-ADC reconstructed energy</p>'
        '<div class="legend"><span id="truth-legend">Truth</span><span id="rec-legend">Reconstructed</span></div>'
        '<svg id="histogram"></svg><script id="pipeline-data" type="application/json">'+payload+'</script>'
        '<script>\n"use strict";\n    const a=bins(truth),b=bins(rec),svg=$("histogram")\n'
        '    put("truth-legend","fixture");\n</script></body></html>')
    (site/'examples/data.json').write_text(payload,encoding='utf-8')
    (site/'examples/pipeline.html').write_text(page,encoding='utf-8')

class RenderTests(unittest.TestCase):
    def test_isolated_narrow_peak_has_two_sides_and_headroom(self):
        counts=[0]*750;counts[662]=1000
        s=toy(counts);g=P.geometry(s)
        x,y=g['x'],g['y']
        self.assertEqual(g['paths'][0],f'M{x(662):.3f},242.000 L{x(662):.3f},{y(1000):.3f} L{x(663):.3f},{y(1000):.3f} L{x(663):.3f},242.000')
        self.assertGreater(y(1000),38+1.4)
        self.assertLess(x(663)-x(662),1)
        self.assertEqual(sum(s['series'][0]['counts']),1000)
    def test_positive_runs_close_at_gap_and_view_ends(self):
        g=P.geometry(toy([1,2,0,1]))
        self.assertEqual(g['paths'][0].count('M'),2)
        self.assertTrue(g['paths'][0].startswith('M70.000,242.000 L70.000,'))
        self.assertIn('L400.000,242.000 M565.000,242.000',g['paths'][0])
        self.assertTrue(g['paths'][0].endswith('L730.000,242.000'))
    def test_masks_keep_data_axes_and_colors_stable(self):
        s=toy([1,0,100]);s['series'].append(copy.deepcopy(s['series'][0]))
        s['series'][0]['label']='Edep - all primaries';s['series'][1]['label']='Erec - accepted only'
        before=copy.deepcopy(s);all_paths=P.geometry(s)['paths']
        for mask in ([True,True],[True,False],[False,True],[False,False]):
            g=P.geometry(s,visible=mask)
            self.assertEqual(g['paths'],[p if show else '' for p,show in zip(all_paths,mask)])
            self.assertEqual(g['high'],P.geometry(s)['high'])
        self.assertEqual(s,before)
        self.assertIn('All series hidden',P.svg(s,visible=[False,False]))
        markup=P.panel(s)
        self.assertEqual(markup.count('type="checkbox"'),2)
        self.assertEqual(markup.count('checked disabled'),2)
        self.assertNotIn('stroke-dasharray',markup)
        self.assertIn('Geant4 deposited-energy truth',markup)
        self.assertIn('Accepted peak-ADC reconstructed energy',markup)
        self.assertEqual(P.presentation(s['series'][0])[1],'#406090')
        self.assertEqual(P.presentation(s['series'][1])[1],'#b05040')
        with self.assertRaises(ValueError):P.geometry(s,visible=[True])
    def test_count_one_not_floor_and_zero_never_logged(self):
        g=P.geometry(toy([0,1,0]))
        self.assertLess(g['y'](1),g['y'](g['low']))
        self.assertEqual(g['paths'][0].count('M'),1)
        self.assertEqual(P.geometry(toy([0,0]))['paths'],[''])
    def test_log_breaks_at_zeros_and_shows_one(self):
        s=toy([1,0,4,4,0,1]); g=P.geometry(s,'log'); path=g['paths'][0]
        self.assertEqual(path.count('M'),3)
        self.assertGreater(g['low'],0);self.assertLess(g['low'],1)
        self.assertLess(g['y'](1),242)
        self.assertIn(1,g['ticks']);self.assertEqual(s['series'][0]['counts'],[1,0,4,4,0,1])
    def test_linear_retains_zero_bins(self):
        g=P.geometry(toy([1,0,4,0]),'linear')
        self.assertEqual(g['paths'][0].count('M'),1)
        self.assertIn(',242.000',g['paths'][0])
    def test_nonuniform_edges_negative_energy_and_empty(self):
        s=toy([1,2,0],[-5,-1,0,7]); g=P.geometry(s)
        self.assertTrue(g['paths'][0].startswith('M70.000,'))
        self.assertIn(f'L{g["x"](-1):.3f}',g['paths'][0])
        self.assertIn('No positive-count bins',P.svg(toy([0,0])))
        self.assertNotIn('NaN',P.svg(toy([1,1])))
    def test_invalid_counts_and_edges_rejected(self):
        for bad in ([-1,2],[True,0],[float('nan'),1]):
            with self.assertRaises(ValueError):toy(bad)
        with self.assertRaises(ValueError):toy([1,2],[0,2,1])
    def test_zoom_exclusion_not_overflow(self):
        s=toy([1,2,3,4]);s['view']=[1,3]
        note=P.accounting(s)[0]
        self.assertIn('5 in view; 5 outside view',note)
        self.assertIn('under/overflow 0/0',note)
    def test_toggle_math_does_not_mutate_data(self):
        s=toy([0,1,50,0]); before=copy.deepcopy(s)
        for mode in ('linear','log','linear','log'):P.geometry(s,mode)
        self.assertEqual(s,before)
    def test_true_log_is_not_log1p(self):
        g=P.geometry(toy([1,10,100]))
        self.assertAlmostEqual(g['y'](1)-g['y'](10),g['y'](10)-g['y'](100))

class SavedDisplayTests(unittest.TestCase):
    def test_source_edit_after_import_fails_before_writes(self):
        before={p.name:p.read_bytes() for p in (self.site/'spectra').iterdir()}
        with patch.dict(D.LOADED_GENERATORS,{'tools/spectrum_plot.py':'0'*64}):
            with self.assertRaisesRegex(ValueError,'sources changed after import'):D.assemble(self.site)
            with self.assertRaisesRegex(ValueError,'sources changed after import'):D.validate(self.site,require_current_generators=True)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.site/'spectra').iterdir()})
    @classmethod
    def setUpClass(cls):
        evidence=ROOT/'.local/student-navigation-v2';evidence.mkdir(parents=True,exist_ok=True)
        cls.tmp=tempfile.TemporaryDirectory(dir=evidence,prefix='spectrum-test-')
        cls.site=Path(cls.tmp.name)
        for rel in tuple(D.ROUTES)+D.DATA_SOURCES+D.RECEIPTS:
            target=cls.site/rel;target.parent.mkdir(parents=True,exist_ok=True)
            if rel not in ('examples/pipeline.html','examples/data.json'):
                shutil.copyfile(ROOT/'docs'/rel,target)
        legacy_pipeline_fixture(cls.site)
        cls.before={rel:D.sha(cls.site/rel) for rel in tuple(D.ROUTES)+D.DATA_SOURCES+D.RECEIPTS}
        cls.manifest=D.assemble(cls.site)
    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()
    def test_complete_coverage(self):
        self.assertEqual([v['plot_states'] for v in self.manifest['pages'].values()],[4,4,10,2])
        self.assertEqual(sum(v['plot_states'] for v in self.manifest['pages'].values()),20)
        self.assertEqual(self.before,{p:D.sha(self.site/p) for p in self.before})
    def test_campaign_returns_and_library_target(self):
        for name,target in (
            ('million-truth','../results/cs137-1m/index.html'),
            ('million-response','../results/cs137-1m/index.html'),
            ('cs137-10k','../results/cs137-10k/index.html'),
            ('pipeline','../results/index.html')):
            page=(self.site/'spectra'/f'{name}.html').read_text(encoding='utf-8')
            self.assertIn(f'href="{target}"',page)
            self.assertIn('Original report (archived presentation)',page)
        for name,dataset in (('million-truth','million'),('million-response','million'),
                             ('cs137-10k','tenk'),('pipeline','teaching')):
            page=(self.site/'spectra'/f'{name}.html').read_text(encoding='utf-8')
            self.assertEqual(page.count('aria-label="Primary"'),1)
            self.assertEqual(page.count('aria-label="Breadcrumb"'),1)
            self.assertEqual(page.count('aria-label="Dataset views"'),1)
            self.assertIn(f'data-dataset="{dataset}"',page)
        response=(self.site/'spectra/million-response.html').read_text(encoding='utf-8')
        other=re.search(r'<section id="other-datasets">(.*?)</section>',response,re.S).group(1)
        self.assertIn('../viewers/events.html?model=AK02&amp;view=positive',other)
        self.assertIn('not from the million-decay campaign',other)
        local=re.search(r'<nav aria-label="Dataset views">(.*?)</nav>',response,re.S).group(1)
        self.assertNotIn('viewers/',local)
    def test_navigation_preserves_all_saved_spectrum_scripts_tables_and_charts(self):
        for destination in D.ROUTES.values():
            before=(ROOT/'docs'/destination).read_text(encoding='utf-8')
            after=(self.site/destination).read_text(encoding='utf-8')
            if destination=='spectra/pipeline.html' and 'id="teaching-data"' in before:
                # This fixture is the older bare-gamma input; today's teaching
                # reader contains six separate saved Cs137 cases instead.
                self.assertEqual(D.embedded_specs(after),D.pipeline_specs(self.site)[:1])
                self.assertEqual(self.before,{p:D.sha(self.site/p) for p in self.before})
                continue
            if destination=='spectra/cs137-10k.html' and len(D.embedded_specs(before))!=len(D.embedded_specs(after)):
                # This fixture deliberately contains AK02/SAP22 only; the real
                # site now also has the separately saved GeRC02/KMRC01 bundle.
                # Compare every fixture spectrum to the matching saved series,
                # rather than equating readers with different dataset coverage.
                expected=D.embedded_specs(after);actual=D.embedded_specs(before)
                self.assertEqual(actual[:len(expected)],expected)
                old=D.component_hashes(before);new=D.component_hashes(after)
                self.assertEqual(old['charts'][:len(expected)],new['charts'])
                self.assertEqual(old['style'],new['style'])
                continue
            self.assertEqual(D.component_hashes(before)['charts'],D.component_hashes(after)['charts'],destination)
            self.assertEqual(D.embedded_specs(before),D.embedded_specs(after),destination)
            # Shared controls and table presentation may change. Every original
            # scientific table remains byte-exact, including precision details.
            for table in re.findall(r'<table\b[^>]*>.*?</table>',before,re.S):
                self.assertIn(table,after,destination)
    def test_repeat_is_byte_and_mtime_exact(self):
        before={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.site/'spectra').iterdir()}
        D.assemble(self.site)
        after={p.name:(p.read_bytes(),p.stat().st_mtime_ns) for p in (self.site/'spectra').iterdir()}
        self.assertEqual(before,after)

    def test_curated_display_never_requires_retired_pipeline_origins(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local',prefix='curated-spectrum-test-') as tmp:
            site=Path(tmp)
            for relative in D.source_inventory(self.site,legacy_teaching=False):
                target=site/relative;target.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(self.site/relative,target)
            def teaching_output(path):
                (path/'spectra/pipeline.html').write_text('<html>Isolated teaching interface fixture</html>')
                (path/'spectra/teaching-examples.json').write_text('{}')
            with patch.object(D,'teaching_available',return_value=True),\
                 patch('teaching_examples.assemble',side_effect=teaching_output),\
                 patch('teaching_examples.validate'):
                result=D.assemble(site)
                self.assertEqual(result['display_revision'],5)
                for relative in ('examples/pipeline.html','examples/data.json'):
                    self.assertNotIn(relative,result['origin_files'])
                    self.assertFalse((site/relative).exists())
                self.assertEqual(D.validate(site,require_current_generators=True),result)
                # Reintroducing an obsolete page does not turn it into a source.
                (site/'examples/pipeline.html').write_bytes(b'retirement stub')
                self.assertEqual(D.assemble(site),result)
                histogram=site/'examples/cs137-1m-response/histograms.json'
                histogram.write_bytes(histogram.read_bytes()+b' ')
                with self.assertRaisesRegex(ValueError,'Original spectrum source changed'):
                    D.validate(site)
    def test_saved_bin_accounting(self):
        truth=D.truth_specs(self.site);response=D.response_specs(self.site)
        self.assertEqual(truth[0]['series'][0]['exact_zero'],987580)
        self.assertEqual(response[0]['series'][0]['total'],12420)
        self.assertEqual(response[0]['series'][1]['total'],10757)
        for specs in (truth,response,D.tenk_specs(self.site),D.pipeline_specs(self.site)):
            for s in specs:P.validate_spec(s)
    def test_rehashed_display_mutation_is_rejected(self):
        path=self.site/'spectra/million-response.html';original=path.read_bytes()
        manifest_path=self.site/'spectra/manifest.json';manifest_bytes=manifest_path.read_bytes()
        try:
            text=original.decode();values=D.embedded_specs(text);changed=copy.deepcopy(values[0])
            changed['series'][0]['counts'][100]+=1;changed['series'][0]['total']+=1
            match=re.search(r'(<script type="application/json" class="spectrum-data">)(.*?)(</script>)',text,re.S)
            text=text[:match.start(2)]+json.dumps(changed,separators=(',',':'))+text[match.end(2):]
            path.write_text(text,encoding='utf-8');m=D.read(manifest_path)
            m['pages']['spectra/million-response.html']['sha256']=D.sha(path)
            manifest_path.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Rendered display|Display bin data'):D.validate(self.site)
        finally:
            path.write_bytes(original);manifest_path.write_bytes(manifest_bytes)
    def test_rehashed_svg_and_control_mutations_are_rejected(self):
        path=self.site/'spectra/million-response.html';original=path.read_bytes()
        mp=self.site/'spectra/manifest.json';saved=mp.read_bytes()
        for old,new in [('class="spectrum-step" d="M','class="spectrum-step" d="M999,'),('Counts / bin (log10 scale)','Incorrect count scale')]:
            try:
                text=original.decode();self.assertIn(old,text)
                path.write_text(text.replace(old,new,1),encoding='utf-8')
                m=D.read(mp);m['pages']['spectra/million-response.html']['sha256']=D.sha(path)
                mp.write_text(json.dumps(m),encoding='utf-8')
                with self.assertRaisesRegex(ValueError,'Static chart|Rendered display'):D.validate(self.site)
            finally:path.write_bytes(original);mp.write_bytes(saved)
    def test_current_generator_policy_does_not_block_saved_snapshot(self):
        mp=self.site/'spectra/manifest.json';saved=mp.read_bytes()
        try:
            m=D.read(mp);m['generators']['tools/spectrum_plot.py']='0'*64
            mp.write_text(json.dumps(m),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Unknown spectrum generator binding'):D.validate(self.site)
            with self.assertRaisesRegex(ValueError,'generator binding'):D.validate(self.site,require_current_generators=True)
        finally:mp.write_bytes(saved)
    def test_reconstructed_edges_must_match_truth(self):
        path=self.site/'examples/cs137-1m-response/histograms.json';saved=path.read_bytes()
        try:
            data=D.read(path);data['AK02']['reconstructed_accepted']['lower_keV']=1
            path.write_text(json.dumps(data),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'edge definitions'):D.response_specs(self.site)
        finally:path.write_bytes(saved)

    def test_pipeline_payload_and_model_states(self):
        m=D.validate(self.site); specs=D.pipeline_specs(self.site)
        self.assertEqual([s['model_id'] for s in specs],['AK02','SAP22'])
        self.assertEqual([len(s['edges']) for s in specs],[25,25])
        page=(self.site/'spectra/pipeline.html').read_text()
        self.assertIn('window.SpectrumUI.update("pipeline-energy",display)',page)
        self.assertNotIn('<svg id="histogram"',page)
        self.assertNotIn('truth-legend',page)
        self.assertNotIn('rec-legend',page)
        self.assertIn('Geant4 deposited-energy truth',page)
        self.assertIn('Accepted peak-ADC reconstructed energy',page)
    def test_current_routes_preserve_original_reports(self):
        p=self.site/'results/index.html';p.parent.mkdir(exist_ok=True)
        p.write_text('<a href="../examples/cs137-1m-response/report.html">Result</a>')
        D.route_current_pages(self.site)
        self.assertIn('../spectra/million-response.html',p.read_text())
        self.assertEqual(self.before,{rel:D.sha(self.site/rel) for rel in self.before})
    def test_campaign_preview_is_semantically_sealed(self):
        home=self.site/D.PREVIEW_PATH;prior=home.read_bytes() if home.exists() else None
        mp=self.site/'spectra/manifest.json';saved=mp.read_bytes()
        try:
            home.parent.mkdir(parents=True,exist_ok=True)
            home.write_text('<html>'+D.homepage_preview(self.site)+'</html>',encoding='utf-8')
            finalized=D.finalize(self.site);D.validate(self.site,require_current_generators=True,require_home=True)
            self.assertNotIn('homepage',finalized)
            self.assertEqual(finalized['campaign_preview']['path'],D.PREVIEW_PATH)
            home.write_text(home.read_text().replace('Counts / bin (log10 scale)','Wrong label',1),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Campaign spectrum rendering'):D.validate(self.site)
        finally:
            mp.write_bytes(saved)
            if prior is None:home.unlink(missing_ok=True)
            else:home.write_bytes(prior)

    def test_home_preview_uses_same_component(self):
        preview=D.homepage_preview(self.site)
        self.assertEqual(D.embedded_specs(preview),D.response_specs(self.site)[::2])
        self.assertEqual([s['key'] for s in D.embedded_specs(preview)],['response-AK02-0','response-SAP22-0'])
        self.assertEqual(preview.count('id="spectrum-controls-script"'),1)
        self.assertEqual(preview.count('id="spectrum-style"'),1)
        self.assertIn('data-scale="log"',preview)

    def test_campaign_preview_rejects_sap22_removal_even_after_resealing(self):
        home=self.site/D.PREVIEW_PATH;prior=home.read_bytes() if home.exists() else None
        mp=self.site/'spectra/manifest.json';saved=mp.read_bytes()
        try:
            home.parent.mkdir(parents=True,exist_ok=True)
            home.write_text('<html>'+D.homepage_preview(self.site)+'</html>',encoding='utf-8')
            finalized=D.finalize(self.site)
            self.assertEqual(finalized['campaign_preview']['models'],['AK02','SAP22'])
            page=home.read_text(encoding='utf-8')
            blocks=re.findall(r'<figure class="spectrum-panel".*?</figure>',page,re.S)
            self.assertEqual(len(blocks),2)
            home.write_text(page.replace(blocks[1],''),encoding='utf-8')
            text,block=D.home_component(self.site)
            metadata=finalized['campaign_preview']
            metadata['panel_sha256']=hashlib.sha256(block.encode()).hexdigest()
            metadata['render_components']=D.component_hashes(text)
            mp.write_text(json.dumps(finalized),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'Campaign spectrum data differs'):
                D.validate(self.site,require_current_generators=True,require_home=True)
        finally:
            mp.write_bytes(saved)
            if prior is None:home.unlink(missing_ok=True)
            else:home.write_bytes(prior)

    def test_four_case_context_uses_saved_variant_and_formal_result_routes(self):
        from ring_site import cases
        site=ROOT/'docs';rows=cases(site);specs=D.tenk_specs(site)
        page=D.four_detector_spectra(site,specs)
        self.assertEqual(D.embedded_specs(page),specs)
        self.assertEqual(len(specs),20)
        state=json.loads(re.search(r'<script id="spectrum-case-context" type="application/json">(.*?)</script>',page,re.S).group(1))
        self.assertEqual(set(state),{row['model'] for row in rows})
        for row in rows:
            model=row['model'];self.assertEqual(state[model]['label'],row['label'])
            self.assertEqual(state[model]['events'],'../viewers/events.html?model='+model+'&view=positive')
            self.assertEqual(state[model]['spectrum'],'cs137-10k.html#tenk-'+model)
            result='../results/cs137-10k/'+model+'/charge-readout.html'
            self.assertEqual(state[model]['result'],result)
            self.assertIn('href="'+result+'">Charge and readout</a>',page)
            self.assertNotIn('href="../'+row['base']+'/response/summary.html"',page)
        for label in ('Primary','Breadcrumb','Dataset views'):
            self.assertEqual(page.count('aria-label="'+label+'"'),1)
        self.assertIn('Compare all 4 detector cases',page)
        self.assertEqual(page.count('data-spectrum-model='),4)
        self.assertEqual(page.count('class="main-spectrum"'),8)
        self.assertNotIn('<details open>',page)

    def test_million_views_keep_two_independent_runs_and_exact_source_tables(self):
        for name in ('truth','response'):
            page=(self.site/f'spectra/million-{name}.html').read_text(encoding='utf-8')
            self.assertIn('1,000,000 initial decays per detector',page)
            self.assertIn('Two independent detector runs',page)
            self.assertNotIn('<h1>Two million',page)
            self.assertEqual(page.count('data-spectrum-model='),2)
            state=json.loads(re.search(r'<script id="spectrum-case-context" type="application/json">(.*?)</script>',page,re.S).group(1))
            for model in ('AK02','SAP22'):
                self.assertEqual(state[model]['truth'],'million-truth.html#million-'+model)
                self.assertEqual(state[model]['response'],'million-response.html#million-'+model)
        truth=(self.site/'spectra/million-truth.html').read_text(encoding='utf-8')
        self.assertEqual(truth.count('class="source-precision"'),2)
        original=(self.site/'examples/cs137-1m/report.html').read_text(encoding='utf-8')
        for table in re.findall(r'<table\b[^>]*>.*?</table>',original,re.S):
            self.assertIn(table,truth)

    def test_campaign_shell_links_to_plots_without_embedding_them(self):
        home=self.site/D.PREVIEW_PATH;prior=home.read_bytes() if home.exists() else None
        mp=self.site/'spectra/manifest.json';saved=mp.read_bytes()
        try:
            home.parent.mkdir(parents=True,exist_ok=True)
            home.write_text('<html><a href="../../spectra/million-truth.html">Truth</a><a href="../../spectra/million-response.html">Response</a></html>',encoding='utf-8')
            finalized=D.finalize(self.site)
            self.assertIn('campaign_shell',finalized);self.assertNotIn('campaign_preview',finalized)
            D.validate(self.site,require_current_generators=True,require_home=True)
            home.write_text(home.read_text().replace('million-response.html','unavailable.html'),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'destination missing'):D.validate_home(self.site,finalized,True)
        finally:
            mp.write_bytes(saved)
            if prior is None:home.unlink(missing_ok=True)
            else:home.write_bytes(prior)

class NavigationCorrectionTests(unittest.TestCase):
    def test_archive_marker_preserves_record_but_rebases_relative_path(self):
        for attrs in ('data-original-report href="{href}"','href="{href}" data-original-report',
                      "data-original-report='true' href='{href}'"):
            for source,target in (
                ('results/cs137-10k/index.html','../../examples/cs137-10k/comparison.html'),
                ('results/cs137-1m/index.html','../../examples/cs137-1m/report.html'),
                ('results/cs137-1m/index.html','../../examples/cs137-1m-response/report.html')):
                original='<a '+attrs.format(href=target+'?saved=1&amp;query=2#original')+'>Archive</a>'
                self.assertEqual(D.rewrite_links(original,source,source),original)
        original='<a title="Record > preview" href="../cs137-10k-hits/hit_event_view.html?model=SAP22&amp;event=0&amp;group=0#recordPanel" data-original-report>Archive</a>'
        moved=D.rewrite_links(original,'examples/cs137-10k/comparison.html','spectra/cs137-10k.html')
        self.assertIn('href="../examples/cs137-10k-hits/hit_event_view.html?model=SAP22&amp;event=0&amp;group=0#recordPanel"',moved)
        self.assertNotIn('../viewers/',moved)
        active='<a class="data-original-report" href="../../examples/cs137-10k/comparison.html#original">Current view</a>'
        self.assertIn('href="../../spectra/cs137-10k.html#original"',D.rewrite_links(active,'results/cs137-10k/index.html','results/cs137-10k/index.html'))

    def test_independent_200_primary_archive_has_no_six_cs137_case_alias(self):
        for marker in ('', 'data-original-report '):
            original='<a '+marker+'href="../examples/pipeline.html?model=AK02#event-0">200-primary bare gamma</a>'
            self.assertEqual(D.rewrite_links(original,'learn/index.html','learn/index.html'),original)

    def test_postmapper_preserves_marked_hub_archives_and_maps_active_links(self):
        with tempfile.TemporaryDirectory(dir=ROOT/'.local/student-navigation-v2',prefix='archive-navigation-') as tmp:
            site=Path(tmp)
            for rel,original,active in (
                ('results/cs137-10k/index.html','../../examples/cs137-10k/comparison.html','../../spectra/cs137-10k.html'),
                ('results/cs137-1m/index.html','../../examples/cs137-1m/report.html','../../spectra/million-truth.html')):
                page=site/rel;page.parent.mkdir(parents=True,exist_ok=True)
                page.write_text('<a data-original-report href="'+original+'">Archive</a><a href="'+original+'">Active</a>',encoding='utf8')
            D.route_current_pages(site)
            for rel,original,active in (
                ('results/cs137-10k/index.html','../../examples/cs137-10k/comparison.html','../../spectra/cs137-10k.html'),
                ('results/cs137-1m/index.html','../../examples/cs137-1m/report.html','../../spectra/million-truth.html')):
                text=(site/rel).read_text(encoding='utf8')
                self.assertIn('<a data-original-report href="'+original+'">Archive</a>',text)
                self.assertIn('<a href="'+active+'">Active</a>',text)
                self.assertEqual(D.rewrite_links(text,rel,rel),text)

    def test_actual_dynamic_headers_contain_initially_hidden_case_actions(self):
        from site_routes import page_navigation
        for rel in ('spectra/cs137-10k.html','viewers/events.html'):
            header=page_navigation(rel,dataset='tenk')
            links={re.search(r'data-context-link="([^"]+)"',tag).group(1):tag
                for tag in re.findall(r'<a\b[^>]*>',header) if 'data-context-link=' in tag}
            self.assertEqual(set(links),{'events','spectrum','result','files'})
            for key in ('result','files'):
                self.assertRegex(links[key],r'\bhidden\b')
                self.assertNotRegex(links[key],r'\shref=')
                self.assertNotIn('AK02',links[key])

    def test_authenticated_intermediate_receipts_are_exact_and_not_rehash_authority(self):
        import viewer_navigation as V
        site=ROOT/'docs';spectrum=site/'spectra/manifest.json';viewer=site/'viewers/manifest.json'
        self.assertIn('36ba63613061e1354d73e6716b528d2cd089eaccea2dd7f090e5633be50326e9',D.TRUSTED_PREVIOUS_MANIFESTS)
        self.assertIn('387e4034bd43932320c53c202bf49d0a805b9d3b61a210f2695baaeb06072e4d',V.TRUSTED_PREVIOUS_UNIFIED_MANIFESTS)
        D.validate(site)
        vm=V.read(viewer)
        # Origin science validation was already performed for this authenticated
        # build. Isolate the receipt trust gate without repeating that scan.
        with patch.object(V,'origins',return_value=vm['original_files']):V.validate(site)
        for module,path,key,error in ((D,spectrum,'generators','Unknown spectrum generator binding'),
                                      (V,viewer,'adapter_sources','Unknown adapter source|Adapter source inventory mismatch')):
            raw=module.read(path);changed=copy.deepcopy(raw);changed[key]['tools/site_routes.py']='0'*64
            changed_bytes=(json.dumps(changed,indent=2)+'\n').encode();changed_hash=module.hashlib.sha256(changed_bytes).hexdigest()
            read_original,sha_original=module.read,module.sha
            def read_candidate(candidate):return changed if Path(candidate)==path else read_original(candidate)
            def sha_candidate(candidate):return changed_hash if Path(candidate)==path else sha_original(candidate)
            with patch.object(module,'read',side_effect=read_candidate),patch.object(module,'sha',side_effect=sha_candidate),\
                 patch.object(V,'origins',return_value=vm['original_files']):
                with self.assertRaisesRegex(ValueError,error):module.validate(site)

class JavaScriptTests(unittest.TestCase):
    @unittest.skipUnless(NODE,'Node needed for saved-case selection')
    def test_selected_case_comparison_history_refresh_and_million_links(self):
        script='''import fs from 'node:fs';import vm from 'node:vm';import assert from 'node:assert/strict';
const code=fs.readFileSync(process.argv[1],'utf8');
function setup(prefix,models,hash,search=''){
 const cases=Object.fromEntries(models.map(model=>[model,{study:'cs137-10k',model,variant:model==='GeRC02'?'GeRC02_Li50min':model,label:model,
   spectrum:'cs137-10k.html#tenk-'+model,result:'result/'+model,files:'files/'+model,
   events:'events.html?model='+model+'&view=positive',
   truth:'million-truth.html#million-'+model,response:'million-response.html#million-'+model}]));
 const node=(dataset={})=>({dataset,hidden:false,textContent:'',attrs:{},listeners:{},
   setAttribute(k,v){this.attrs[k]=v;},removeAttribute(k){delete this.attrs[k];delete this[k];},addEventListener(k,fn){this.listeners[k]=fn;}});
 const select=node({prefix}),status=node(),payload=node(),focus=node(),context=node(),listeners={},returnBox=node(),returnEvent=node(),return3D=node();
 payload.textContent=JSON.stringify(cases);
 const sections=models.map(spectrumModel=>node({spectrumModel}));
 const links=['spectrum','result','files','truth','response','events'].map(contextLink=>node({contextLink,baseHref:contextLink+'.html'})),caseLinks=models.map(model=>node({spectrumCaseLink:'result',caseModel:model,baseHref:cases[model].result}));
 const location={hash,pathname:'/spectra/test.html',search},move=url=>{const u=new URL(url,'https://test.invalid');location.hash=u.hash;location.search=u.search;},history={state:null,replaceState(_s,_t,url){move(url);},pushState(_s,_t,url){move(url);}};
 const document={readyState:'complete',getElementById:id=>({'spectrum-case':select,'spectrum-focus':status,'spectrum-case-context':payload,'spectrum-return-context':returnBox,'spectrum-return-event':returnEvent,'spectrum-return-3d':return3D})[id],
   querySelectorAll:q=>({'.spectrum-panel':[],'[data-spectrum-model]':sections,'[data-dataset]':[context],'[data-context-label]':[focus],'[data-context-link]':links,'[data-spectrum-case-link]':caseLinks})[q]||[]};
 const c=vm.createContext({document,location,history,URLSearchParams,addEventListener:(k,fn)=>listeners[k]=fn});vm.runInContext(code,c);
 return {c,location,select,sections,links,status,listeners,returnBox,returnEvent,return3D,caseLinks};
}
const models=['AK02','SAP22','GeRC02','KMRC01_candidate'];
let v=setup('tenk',models,'');assert.equal(v.location.hash,'#tenk-AK02');
assert.deepEqual(v.sections.map(s=>s.hidden),[false,true,true,true]);
for(const model of models){v.select.value=model;v.select.listeners.change();
 assert.equal(v.location.hash,'#tenk-'+model);assert.deepEqual(v.sections.map(s=>s.hidden),models.map(m=>m!==model));
 v.location.hash='#tenk-'+model;v.listeners.popstate();assert.equal(v.select.value,model);
 assert.equal(setup('tenk',models,v.location.hash).select.value,model);}
v.location.hash='#compare';v.listeners.hashchange();assert.equal(v.select.value,'compare');assert.ok(v.sections.every(s=>!s.hidden));
assert.equal(v.links[0].href,'spectrum.html#compare');assert.equal(v.links[1].href,undefined);
v.location.hash='#tenk-missing';v.listeners.popstate();assert.ok(v.sections.every(s=>s.hidden));assert.match(v.status.textContent,/Unavailable/);
for(const model of ['AK02','SAP22']){v=setup('million',['AK02','SAP22'],'#million-'+model);
 assert.deepEqual(v.sections.map(s=>s.hidden),['AK02','SAP22'].map(m=>m!==model));
 assert.equal(v.links[3].href,'million-truth.html#million-'+model);assert.equal(v.links[4].href,'million-response.html#million-'+model);}
const original='?study=cs137-10k&model=AK02&variant=AK02&event=698&group=0';
v=setup('tenk',models,'#tenk-AK02',original);
for(const link of [v.links[1],v.links[2],v.links[5],v.caseLinks[0],v.returnEvent,v.return3D]){const q=new URL(link.href,'https://test.invalid').searchParams;assert.equal(q.get('study'),'cs137-10k');assert.equal(q.get('model'),'AK02');assert.equal(q.get('variant'),'AK02');assert.equal(q.get('event'),'698');assert.equal(q.get('group'),'0');}
assert.equal(v.returnEvent.textContent,'Return to AK02 event 698 / group 0');assert.equal(v.returnBox.hidden,false);
v.select.value='compare';v.select.listeners.change();assert.equal(new URLSearchParams(v.location.search).get('event'),'698');assert.equal(v.returnBox.hidden,false);assert.ok(v.sections.every(s=>!s.hidden));
assert.equal(setup('tenk',models,v.location.hash,v.location.search).returnEvent.textContent,'Return to AK02 event 698 / group 0');
v.select.value='AK02';v.select.listeners.change();assert.equal(new URLSearchParams(v.location.search).get('event'),'698');
v.select.value='SAP22';v.select.listeners.change();let changed=new URLSearchParams(v.location.search);assert.equal(changed.get('model'),'SAP22');assert.equal(changed.get('variant'),'SAP22');assert.equal(changed.has('event'),false);assert.equal(changed.has('group'),false);assert.equal(v.returnBox.hidden,true);
v.location.search=original;v.location.hash='#tenk-AK02';v.listeners.popstate();assert.equal(v.returnEvent.textContent,'Return to AK02 event 698 / group 0');assert.equal(v.returnBox.hidden,false);
for(const bad of ['?study=cs137-1m&model=AK02&event=698&group=0','?model=GeRC02&variant=GeRC02_Li30min&event=61&group=0','?model=AK02&event=698&group=1.5']){v=setup('tenk',models,'#tenk-AK02',bad);assert.ok(v.sections.every(s=>s.hidden));assert.match(v.status.textContent,/Unavailable|Invalid|differs/);assert.equal(v.returnBox.hidden,true);}
console.log('Saved-case selection, explicit comparison, history and refresh passed');'''
        result=subprocess.run([NODE,'--input-type=module','-e',script,str(ROOT/'tools/spectrum_controls.js')],capture_output=True,text=True,timeout=20,check=True)
        self.assertIn('passed',result.stdout)

    @unittest.skipUnless(NODE,'Node needed for browser-math parity')
    def test_js_log_linear_parity(self):
        source=(ROOT/'tools/spectrum_controls.js').read_text()
        self.assertNotIn('Math.log1p',source)
        fixtures=[toy([1,0,10,100,0,1]),toy([0,0]),toy([1,1]),toy([5,0,2],[-5,-1,2,7]),toy([0]*662+[1000]+[0]*87)]
        for s in fixtures:s['series'].append(copy.deepcopy(s['series'][0]))
        script='''import fs from 'node:fs'; import vm from 'node:vm';
const context={};vm.createContext(context);vm.runInContext(fs.readFileSync(process.argv[1],'utf8'),context);
const data=JSON.parse(process.argv[2]);const before=JSON.stringify(data);
const out=data.map(s=>['log','linear'].flatMap(mode=>[[true,true],[true,false],[false,true],[false,false]].map(mask=>{const g=context.SpectrumUI.geometry(s,mode,mask);return {paths:g.paths,ticks:g.ticks,low:g.low,high:g.high};})));
if(JSON.stringify(data)!==before)throw Error('Mutated bins');process.stdout.write(JSON.stringify(out));'''
        result=subprocess.run([NODE,'--input-type=module','-e',script,str(ROOT/'tools/spectrum_controls.js'),json.dumps(fixtures)],capture_output=True,text=True,timeout=20,check=True)
        actual=json.loads(result.stdout)
        for s,states in zip(fixtures,actual):
            cases=[(mode,mask) for mode in ('log','linear') for mask in ([True,True],[True,False],[False,True],[False,False])]
            for (mode,mask),state in zip(cases,states):
                expected=P.geometry(s,mode,mask)
                for key in ('paths','ticks','low','high'):self.assertEqual(state[key],expected[key])

if __name__=='__main__':unittest.main(verbosity=2)
