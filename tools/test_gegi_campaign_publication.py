"""Tiny synthetic saved-artifact fixtures only; no science or real site build."""
import copy
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import Mock,patch

import gegi_campaign as C
import gegi_campaign_analysis as A
import gegi_campaign_publication as P
import gegi_event_store as S
import scenario_workflow as W


class CampaignPublication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-publication-test-',dir=P.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.base=Path(self.temp.name)
        self.campaign=self.base/'campaign';self.analysis=self.base/'analysis'
        self.campaign.mkdir();self.analysis.mkdir();self.output=self.base/'export'
        self.plan=C.draft()
        for g in self.plan['groups']:
            g['primary_count']=10;g['partition']=C.B.partition(10,g['master_seed'])
        self.plan['total_initial_primaries']=40
        self.plan['source_sha256']={**C.source_pins(P.ROOT),**A.source_hashes(P.ROOT)}
        request=self.base/'request.json';W.write(request,{'numerics':{'field_policy':'reuse-only'},
            'field_cache':{'sha256':'f'*64},'profile_sha256':'e'*64})
        self.plan['native_request']={'ref':request.relative_to(P.ROOT).as_posix(),'sha256':W.sha(request)}
        self.plan['calibration']={'sha256':'a'*64};self.plan['transport_context']={}
        self.plan['physics_sha256']=C.physics_sha256(self.plan)
        W.write(self.campaign/'plan.json',self.plan)
        self.channels=[]
        for i in range(1,35):
            trace={'time_ns':[0.,1.,2.],'charge_fC':[0.,-.1234567890123456,-.2],
                   'current_nA':[0.,.1,.2],'preamp_V':[0.,.001,.002],'shaped_V':[0.,.003,.004]}
            self.channels.append({'contact_id':i,'accepted':True,'reconstructed_energy_keV':10.,
                'final_induced_keV':20. if i in (1,2,18,19) else 0.,'trace':trace})
        recipe={'channels':[{'id':i} for i in range(1,35)],'readout_config':{},'electronics_calibration':{},
                'ionisation_energy_eV':2.96,'drift_dt_ns':1.,
                'source_code_sha256':{'gegi_campaign_response.jl':'1'*64}}
        self.recipe_sha=W.digest(recipe);inputs=[];groups={};maps={};complete_groups={};chunk_hashes={}
        for chunk in C.chunks(self.plan):
            key=chunk['source_group'];g=next(x for x in self.plan['groups'] if x['id']==key)
            folder=C.chunk_path(self.campaign,chunk);folder.mkdir(parents=True)
            identity=C.chunk_identity(self.campaign,self.plan,chunk)
            event={'event_id':9,'group_id':0,'status':'completed','channels':copy.deepcopy(self.channels),
                'input_group':{'primary_time_ns':0.,'group_origin_time_ns':10000000.},'readout_horizon_ns':100000.,
                'readout_recipe_sha256':self.recipe_sha,'calibration_sha256':'a'*64,
                'photopeak_windows_sha256':identity['photopeak_windows_sha256'],
                'reconstruction':{'status':'accepted','ordering_ambiguous':False,'pairing_ambiguous':False,
                    'paired_site_hypotheses':[{'pairing_index':0,'valid_order_count':1,'sites':[
                        {'x_contact':1,'y_contact':18,'position_mm':[0.,0.,0.],'energy_keV':300.,'ctd_ns':2.,'method':'synthetic_unit_fixture'},
                        {'x_contact':2,'y_contact':19,'position_mm':[10.,0.,0.],'energy_keV':362.,'ctd_ns':3.,'method':'synthetic_unit_fixture'}]}],
                    'cones':[{'vertex_mm':[0.,0.,0.],'axis':[-1.,0.,0.],
                        'half_angle_deg':math.degrees(math.acos(1-510.99895069*(1/362.-1/662.))),
                        'cos_theta':1-510.99895069*(1/362.-1/662.),
                        'scatter_energy_keV':300.,'absorbed_energy_keV':362.,'site_separation_mm':10.,
                        'weight':1.,'pairing_index':0,'order':[0,1]}]},
                'readout_summary':{'accepted':True,'energy_keV':662.}}
            native={i:{'time_ns':[0.,1.,2.],'signed_induced_keV':[0.,.1,.2]} for i in range(1,35)}
            counts={name:0 for name in A.COUNT_FIELDS}
            counts.update(initial_primaries=10,zero_deposit_primaries=9,nonzero_primaries=1,pulse_groups=1,
                readout_accepted_groups=1,readout_accepted_primaries=1,imaging_accepted_groups=1,imaging_accepted_primaries=1)
            td={} if g['source']==C.GAMMA else {'initial_decays':10,'decay_photons':17,'line_photons':9,'line_photon_counts':{'fixture':9}}
            response={'counts':counts|td,'status':'completed','readout_recipe':recipe,'readout_recipe_sha256':self.recipe_sha}
            db=folder/'events.sqlite';store=S.Store(db,identity,create=True)
            try:
                store.append(9,0,event,native,W.digest(event));store.seal(response);saved,_=store.read(9,0)
            finally:store.close()
            done={'identity':identity,'response':response,'artifacts':{'events.sqlite':{'sha256':W.sha(db),'bytes':db.stat().st_size}}}
            W.write(folder/'DONE.json',done);chunk_hashes[str(chunk['chunk_index'])]=W.sha(folder/'DONE.json')
            store_ref=db.relative_to(self.campaign).as_posix()
            rep_id={'source_group':key,'chunk_index':chunk['chunk_index'],'raw_primary_id':9,'pulse_group_id':0,
                    'source_global_initial_id':9,'campaign_initial_id':chunk['campaign_initial_offset']+9}
            rep=A.representative(saved,rep_id,store_ref,W.sha(db))
            bins=[0]*2000;bins[331]=1
            groups[key]={'source':g['source'],'count_unit':g['count_unit'],'initial_primary_denominator':10,
                'counts':counts,'transport_denominators':td,'representative':rep,'native_status_counts':{'completed':1},
                'readout_rejection_reasons':{},'rejection_reasons':{},'truth_position_mm_for_evaluation_only':g['source_position_mm'],
                'spectrum':{'edges_keV':[2.*i for i in range(2001)],'counts':bins,'underflow':0,'overflow':0,'selected_readout_groups':1},
                'evaluations':{'direction':{'status':'inconclusive'},'plane':{'status':'inconclusive'}}}
            maps[key]={window:self.pair() for window in ('all','661.657','1173.228','1332.492')}
            inputs.append({'source_group':key,'chunk_index':chunk['chunk_index'],'done_sha256':W.sha(folder/'DONE.json'),
                'store_ref':store_ref,'store_sha256':W.sha(db),'initial_primaries':10,'radiation_seed':chunk['batch']['radiation_seed']})
            complete_groups[key]=counts|td
        mixtures={};mixture_maps={}
        for a,b in (('gamma-left','gamma-right'),('cs137-left','co60-right')):
            key=a+'__'+b;mixtures[key]={'components':[a,b],'normalization':A.criteria()['mixture_rule'],
                'independence':'No inter-source pileup model.','evaluations':{'direction':{'status':'inconclusive'},'plane':{'status':'inconclusive'}}}
            mixture_maps[key]={window:self.pair() for window in ('all','661.657','1173.228','1332.492')}
        W.write(self.campaign/'COMPLETE.json',{'status':'completed','plan_sha256':W.sha(self.campaign/'plan.json'),
            'physics_sha256':self.plan['physics_sha256'],'initial_primaries':40,'groups':complete_groups,'chunks':chunk_hashes})
        self.summary={'kind':A.KIND,'status':'complete','campaign_id':'synthetic-unit-fixture','criteria':A.criteria(),
            'analysis_revision':A.validate_analysis_revision(self.plan,root=P.ROOT),
            'source_sha256':A.source_hashes(P.ROOT),'plan_sha256':W.sha(self.campaign/'plan.json'),
            'physics_sha256':self.plan['physics_sha256'],'processed_initial_records':40,'planned_initial_records':40,
            'inputs':inputs,'groups':groups,'mixtures':mixtures,'count_scope':'Initial primaries and pulse groups remain distinct.',
            'limitations':['Synthetic unit fixture; never published.','The plane is assumed; no true 3D reconstruction.']}
        W.write(self.analysis/'summary.json',self.summary)
        W.write(self.analysis/'maps.json',{'kind':A.KIND,'criteria':A.criteria(),'groups':maps,'mixtures':mixture_maps})
        (self.analysis/'cones.jsonl').write_bytes(b'')
        self.seal_analysis()

    @staticmethod
    def pair():
        return {'direction':{'azimuth_deg':[-180.,0.],'elevation_deg':[-45.,45.],'values':[[0.,1.],[2.,0.]],'value_units':'weighted accepted groups per steradian'},
                'plane':{'x_mm':[-1.,1.],'y_mm':[-1.,1.],'plane_z_mm':40.,'values':[[0.,1.],[2.,0.]],'value_units':'weighted accepted groups per square millimetre'}}

    def seal_analysis(self):
        W.write(self.analysis/'manifest.json',{'kind':A.KIND,'status':'complete','plan_sha256':self.summary['plan_sha256'],
            'analysis_revision':self.summary.get('analysis_revision'),
            'source_sha256':self.summary['source_sha256'],'radiation_calls':0,'field_solves':0,
            'files':{name:{'sha256':W.sha(self.analysis/name),'bytes':(self.analysis/name).stat().st_size}
                     for name in ('summary.json','maps.json','cones.jsonl','bootstrap.json') if (self.analysis/name).is_file()}})

    def fake_replay(self,request,output,log,**kwargs):
        value={'drift_executed':False,'channels':copy.deepcopy(self.channels)}
        W.write(output,value);Path(log).write_text('Synthetic test replay; no Julia or physics.')
        return value

    def export(self,**kwargs):
        with patch.object(C,'read_plan',return_value=self.plan):
            return P.export(self.campaign,self.analysis,self.output,exporter_sha256=W.sha(P.__file__),replayer=self.fake_replay,**kwargs)

    def test_complete_compact_bundle_preserves_denominators_clock_and_signal_identity(self):
        target=self.export();record=P.validate_bundle(target)
        self.assertLess(sum(p.stat().st_size for p in target.iterdir()),P.MAX_BUNDLE_BYTES)
        self.assertEqual(record['electronics_replays'],4);self.assertEqual(record['native_drift_calls'],0)
        reps=W.read(target/'representatives.json');self.assertEqual(reps['cs137-left']['group_origin_time_ns'],10000000.)
        self.assertEqual(len(reps['co60-right']['native_reference_channels']),34)
        public=W.read(target/'summary.json');self.assertEqual(public['groups']['co60-right']['transport_denominators']['decay_photons'],17)
        self.assertEqual(public['groups']['gamma-left']['spectrum']['counts'][331],1)
        self.assertNotIn('store_ref',public['inputs'][0]);page=(target/'index.html').read_text(encoding='utf-8')
        for text in ('661.657','1173.228','1332.492','inconclusive','100 µs','not a recovered distance',
                     'gegi_signal_journey.js','no inter-source pileup'):
            self.assertIn(text.lower(),page.lower())
        self.assertNotIn('../../examples/gegi/index.html',page)
        self.assertNotIn('earlier 10k',page.lower())
        self.assertNotIn('channels',reps['co60-right'])
        embedded=json.loads(re.search(r'<script type="application/json" id="gegi-journey-data">(.*?)</script>',page,re.S)[1])
        representative=embedded['groups']['co60-right']['representative']
        self.assertEqual(len(representative['channels']),34)
        self.assertEqual(representative['channels'][0]['trace']['charge_fC'][1],-.1234567890123456)
        self.assertEqual(representative['reconstruction']['cones'][0]['weight'],1.)
        self.assertEqual((target/'gegi_signal_journey.js').read_bytes(),(P.ROOT/P.DISPLAY_SOURCE).read_bytes())
        self.assertFalse(any(p.suffix in ('.sqlite','.jsonl') for p in target.iterdir()))

    def test_partial_tampered_analysis_or_exporter_is_refused_before_output(self):
        with self.assertRaisesRegex(ValueError,'Freeze the exporter'):
            P.export(self.campaign,self.analysis,self.output,exporter_sha256='0'*64)
        self.summary['status']='partial_sealed_chunks';W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'Only complete'):
            P.saved_inputs(self.campaign,self.analysis)
        self.summary['status']='complete';W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        (self.analysis/'maps.json').write_bytes(b'{}')
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'Analysis artifact changed'):
            P.saved_inputs(self.campaign,self.analysis)
        self.assertFalse(self.output.exists())

    def test_representative_native_tamper_or_inexact_replay_is_refused(self):
        group=self.summary['groups']['gamma-left']
        def wrong(request,output,log,**kwargs):
            value=self.fake_replay(request,output,log);value['channels'][0]['trace']['charge_fC'][1]+=1e-12
            W.write(output,value);return value
        with self.assertRaisesRegex(ValueError,'trace mismatch'):
            P.representative(self.campaign,group,self.base/'wrong-replay',replayer=wrong)
        database=self.campaign/group['representative']['store_ref']
        with database.open('ab') as stream:stream.write(b'changed synthetic Store')
        never=Mock(side_effect=AssertionError('No replay of changed native Store'))
        with self.assertRaisesRegex(ValueError,'Store changed'):
            P.representative(self.campaign,group,self.base/'refused',replayer=never)
        never.assert_not_called()

    def test_signal_png_respects_each_channels_exact_display_time_grid(self):
        replay={'channels':copy.deepcopy(self.channels)}
        replay['channels'][1]['trace']['time_ns']=[0.,.25,3.]
        destination=self.base/'individual-times.png'
        P.signal_figure(replay,destination,'Synthetic channel-grid check')
        self.assertTrue(destination.is_file())

    def test_shared_display_math_matches_frozen_candidate_weights_and_maps(self):
        node=shutil.which('node')
        self.assertIsNotNone(node,'Existing Node runtime is required for the shared display check')
        import gegi_imaging as I
        first={'position_mm':[2.,-3.,1.],'energy_keV':300.}
        second={'position_mm':[13.,5.,-1.],'energy_keV':362.}
        cones=[I.cone(first,second),I.cone(second,first)]
        for cone in cones:cone['weight']=.5
        script=('const J=require('+json.dumps(str(P.ROOT/P.DISPLAY_SOURCE))+');'+
            'const c='+json.dumps(cones)+';'+
            'const ev={reconstruction:{status:"accepted",cones:c},sites:[{truth:"ignored"}]};'+
            'const before=JSON.stringify(ev);const valid=J.validCones(ev);'+
            'const bad={reconstruction:{status:"accepted",cones:[c[0],{...c[1],weight:0}]}};'+
            'console.log(JSON.stringify({ray:J.coneRay(c[0],73),direction:J.directionMap(valid),plane:J.planeMap(valid),'+
            'unchanged:before===JSON.stringify(ev),retained:valid.length,malformed:J.validCones(bad).length}));')
        result=subprocess.run([node,'-e',script],capture_output=True,text=True,check=True)
        display=json.loads(result.stdout);ray=display['ray'];cone=cones[0]
        self.assertTrue(display['unchanged']);self.assertEqual(display['retained'],2);self.assertEqual(display['malformed'],0)
        self.assertAlmostEqual(sum(v*v for v in ray),1.,places=12)
        self.assertAlmostEqual(sum(a*b for a,b in zip(ray,cone['axis'])),math.cos(math.radians(cone['half_angle_deg'])),places=12)
        for actual,expected in ((display['direction'],I.backproject(cones)),(display['plane'],A.plane_backproject(cones))):
            delta=max(abs(a-b) for ar,br in zip(actual['values'],expected['values']) for a,b in zip(ar,br))
            self.assertLess(delta,2e-12)
        self.assertAlmostEqual(sum(sum(row)*area for row,area in zip(display['direction']['values'],display['direction']['areas'])),1.,places=12)
        self.assertAlmostEqual(sum(map(sum,display['plane']['values']))*4.,1.,places=12)

    def test_exact_native_failure_and_exclusive_counts_are_readable_and_escaped(self):
        group=self.summary['groups']['gamma-left']
        group['native_error_counts']={'ArgumentError: <exact & saved>':2}
        group['exclusive_stage_counts']={'native_failed':2,'imaging_accepted':1}
        page=P.render(self.summary,[],{}).decode()
        self.assertIn('Exact saved native error',page)
        self.assertIn('ArgumentError: &lt;exact &amp; saved&gt;',page)
        self.assertIn('First unsuccessful stage / accepted outcome (exclusive)',page)
        self.assertNotIn('ArgumentError: <exact & saved>',page)

    def test_checked_bootstrap_is_compact_conditional_peak_variation(self):
        n=A.criteria()['bootstrap']['resamples']
        groups={key:{kind:[{'replicate':i,'accepted_groups':1,'bias':float(i),
            'peak':{'x_mm':119. if i%2==0 else 0.,'y_mm':0.} if kind=='plane' else {'azimuth_deg':0.}}
            for i in range(n)] for kind in ('direction','plane')} for key in self.summary['groups']}
        saved={'kind':'gegi_campaign_bootstrap_v1','policy':A.criteria()['bootstrap'],'groups':groups,
               'runtime_seconds':1.25,'limitations':['Synthetic conditional peak variation; no hardware uncertainty.']}
        W.write(self.analysis/'bootstrap.json',saved)
        self.summary['bootstrap']={'requested':True,'status':'complete','output':'bootstrap.json'}
        W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        target=self.export();record=P.validate_bundle(target);report=W.read(target/'bootstrap-summary.json')
        value=report['groups']['gamma-left']['plane']
        self.assertEqual(report['source_bootstrap_sha256'],W.sha(self.analysis/'bootstrap.json'))
        for name,expected in {'p2_5':4.975,'p50':99.5,'p97_5':194.025}.items():
            self.assertAlmostEqual(value['peak_offset_percentiles'][name],expected,places=12)
        self.assertEqual(value['within_fixed_localization_tolerance_replicates'],16)
        self.assertEqual(value['finite_plane_boundary_peak_replicates'],100)
        self.assertNotIn('bootstrap.json',record['artifacts'])
        page=(target/'index.html').read_text(encoding='utf-8')
        self.assertIn('Conditional finite-sample peak variation',page)
        self.assertIn('No resampled mixture-separation probability was computed',page)
        (self.analysis/'bootstrap.json').write_bytes(b'{}')
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'Analysis artifact changed'):
            P.saved_inputs(self.campaign,self.analysis)

    def test_source_assessment_is_bound_to_same_analysis_and_never_reports_assumed_range(self):
        def item(evaluations):
            return {'spectral_inference':{'status':'ambiguous','interpretation':'A line is supported; source identity remains ambiguous.',
                'candidate_components':[{'id':'line','label':'Cs137/Ba137m or monoenergetic 662 keV','status':'ambiguous',
                    'reason':'A single line cannot identify its production mechanism.','alternatives':['monoenergetic gamma']}],
                'line_evidence':[{'line_energy_keV':661.657,'peak_bin_center_keV':663.,'signal_counts':3.,
                    'continuum_estimate_counts':1.,'net_excess_counts':2.,'status':'synthetic screening only'}],
                'limitations':['Not a calibrated detection significance.']},
                'distance':{'status':'not_identified_by_saved_analysis','distance_mm':None,'assumed_plane_z_mm':40.,
                    'reason':'The source plane is assumed; range has not been fitted.'},'imaging_evaluation':evaluations}
        folder=self.base/'source-inference';folder.mkdir();path=folder/'report.json'
        provenance={'analysis_manifest_sha256':W.sha(self.analysis/'manifest.json'),'summary_sha256':W.sha(self.analysis/'summary.json'),
            'maps_sha256':W.sha(self.analysis/'maps.json'),'cones_sha256':W.sha(self.analysis/'cones.jsonl'),
            'plan_sha256':self.summary['plan_sha256'],'validation_scope':'Synthetic saved-input contract only.'}
        report={'kind':'gegi_source_inference_v1','provenance':provenance,
            'groups':{key:item(g['evaluations']) for key,g in self.summary['groups'].items()},
            'mixtures':{key:item(g['evaluations']) for key,g in self.summary['mixtures'].items()},'references':[]}
        W.write(path,report)
        manifest={'kind':report['kind'],'status':'complete_posthoc_diagnostic','provenance':provenance,
            'source_sha256':{'tools/gegi_campaign_publication.py':W.sha(P.__file__)},
            'files':{'report.json':{'sha256':W.sha(path),'bytes':path.stat().st_size}}}
        W.write(folder/'manifest.json',manifest)
        target=self.export(source_assessment=path);P.validate_bundle(target)
        self.assertEqual(W.read(target/'source-assessment.json'),report)
        page=(target/'index.html').read_text(encoding='utf-8')
        self.assertIn('No source distance is identified',page)
        self.assertIn('Cs137/Ba137m or monoenergetic 662 keV',page)
        self.assertIn('not an exhaustive nuclide search',page)
        inputs={'analysis_manifest_sha256':provenance['analysis_manifest_sha256'],
            **{name+'.json_sha256':provenance[name+'_sha256'] for name in ('summary','maps')},
            'cones.jsonl_sha256':provenance['cones_sha256']}
        report['provenance']['summary_sha256']='0'*64;W.write(path,report)
        manifest['files']['report.json']={'sha256':W.sha(path),'bytes':path.stat().st_size};W.write(folder/'manifest.json',manifest)
        with self.assertRaisesRegex(ValueError,'different saved analysis'):
            P.source_report(path,self.summary,inputs)

    def test_representative_preserves_verified_prior_recipe_after_failure_policy_repair(self):
        from contextlib import closing
        import sqlite3
        group=copy.deepcopy(self.summary['groups']['gamma-left'])
        database=self.campaign/group['representative']['store_ref']
        done=W.read(database.parent/'DONE.json');response=done['response']
        old_recipe=copy.deepcopy(response['readout_recipe']);old_sha=W.digest(old_recipe)
        with A.scalar_store(database,done['identity'],response) as store:
            event,_=store.read(9,0)
            input_sha=store.db.execute('SELECT input_sha256 FROM events WHERE primary_id=9 AND group_id=0').fetchone()[0]
        response['readout_recipe']['source_code_sha256']['gegi_campaign_response.jl']='2'*64
        response['readout_recipe_sha256']=W.digest(response['readout_recipe'])
        response['prior_recipe_provenance']={
            'kind':'gegi_prior_recipe_provenance_v1','revision':{'ref':'revisions/failure-policy-v2.json','sha256':'3'*64},
            'original_store_sha256':W.sha(database),'recipes':{old_sha:old_recipe},
            'events':[{'event_id':9,'group_id':0,'input_sha256':input_sha,
                       'metadata_sha256':W.digest(event),'readout_recipe_sha256':old_sha}],
            'wrapper_source_change':{'name':'gegi_campaign_response.jl','old_sha256':'1'*64,'new_sha256':'2'*64}}
        with closing(sqlite3.connect(database)) as db:
            with db:
                db.execute('UPDATE completion SET body=? WHERE singleton=1',(S.encoded(response),))
        digest=W.sha(database);done['artifacts']['events.sqlite']['sha256']=digest
        W.write(database.parent/'DONE.json',done);group['representative']['store_sha256']=digest
        def replay(request,output,log,**kwargs):
            self.assertEqual(W.read(request)['source_code_sha256'],old_recipe['source_code_sha256'])
            return self.fake_replay(request,output,log,**kwargs)
        record,_=P.representative(self.campaign,group,self.base/'prior-recipe-replay',replayer=replay)
        self.assertEqual(record['readout_recipe_sha256'],old_sha)
        self.assertEqual(record['readout_source_code_sha256'],old_recipe['source_code_sha256'])
        self.assertEqual(record['replay']['channels'],34)

    def test_publication_uses_verified_explicit_revision_and_refuses_forged_metadata(self):
        original=copy.deepcopy(self.summary['analysis_revision'])
        with patch.object(C,'read_plan',return_value=self.plan),\
             patch.object(A,'validate_analysis_revision',wraps=A.validate_analysis_revision) as verify:
            P.saved_inputs(self.campaign,self.analysis)
        verify.assert_called_once_with(self.plan,root=P.ROOT,allow_analysis_revision=False)
        self.summary['analysis_revision']['original_analysis_sha256']='0'*64
        W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'revision metadata differs'):
            P.saved_inputs(self.campaign,self.analysis)
        self.summary['analysis_revision']=copy.deepcopy(original);self.summary['analysis_revision']['allowed']=True
        W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        self.plan['source_sha256']['tools/gegi_imaging.py']='0'*64
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'Frozen producer source changed'):
            P.saved_inputs(self.campaign,self.analysis)
        self.plan['source_sha256']['tools/gegi_imaging.py']=W.sha(P.ROOT/'tools/gegi_imaging.py')
        del self.summary['analysis_revision'];W.write(self.analysis/'summary.json',self.summary);self.seal_analysis()
        with patch.object(C,'read_plan',return_value=self.plan),self.assertRaisesRegex(ValueError,'Explicit matching analysis revision'):
            P.saved_inputs(self.campaign,self.analysis)

    def test_saved_copy_links_are_idempotent_and_old_result_stays_separate(self):
        target=self.export();site=self.base/'site'
        for name in ('index.html','results/index.html','detectors/GeGI_3D/index.html','detectors/GeGI_3D/technical.html','assemblies/gegi/index.html','examples/gegi/index.html'):
            p=site/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('<html><main>Preserve earlier saved result</main></html>')
        historical=(site/'examples/gegi/index.html').read_bytes()
        assembly=(site/'assemblies/gegi/index.html').read_bytes()
        P.install_bundle(target,site);P.link_current(site);first=(site/'results/index.html').read_bytes()
        P.link_current(site);self.assertEqual((site/'results/index.html').read_bytes(),first)
        self.assertIn(b'gegi-campaign/index.html',first);self.assertEqual((site/'examples/gegi/index.html').read_bytes(),historical)
        self.assertEqual((site/'assemblies/gegi/index.html').read_bytes(),assembly)
        P.validate_bundle(site/'results/gegi-campaign')
        (target/'summary.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'artifact changed'):P.validate_bundle(target)

    def test_normal_build_dispatch_copies_saved_bundle_without_export_or_replay(self):
        import build_site as B
        import viewer_navigation as V
        target=self.export();site=self.base/'source-site';site.mkdir()
        (site/'index.html').write_text('<html><main>Saved</main></html>')
        (site/B.MANIFEST).write_text('{}');out=self.base/'.local/site-build'
        with patch.object(B,'ROOT',self.base),patch.object(B,'DESTINATION',site),patch.object(B,'OUT',out),\
             patch.object(B,'validate',return_value={}),patch.object(B,'install_snapshot',return_value='mock-staged'),\
             patch.object(V,'assemble'),patch.object(P,'export',side_effect=AssertionError('Build cannot export/replay')):
            result=B.build(gegi_campaign_bundle=target)
        self.assertEqual(result,'mock-staged');P.validate_bundle(out/'results/gegi-campaign')
        self.assertIn('gegi-campaign/index.html',(out/'index.html').read_text(encoding='utf-8'))


if __name__=='__main__':unittest.main()
