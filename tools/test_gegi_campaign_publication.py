"""Tiny synthetic saved-artifact fixtures only; no science or real site build."""
import copy
from pathlib import Path
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
                'reconstruction':{'status':'accepted','ordering_ambiguous':False,'pairing_ambiguous':False},
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
                     for name in ('summary.json','maps.json','cones.jsonl')}})

    def fake_replay(self,request,output,log,**kwargs):
        value={'drift_executed':False,'channels':copy.deepcopy(self.channels)}
        W.write(output,value);Path(log).write_text('Synthetic test replay; no Julia or physics.')
        return value

    def export(self):
        with patch.object(C,'read_plan',return_value=self.plan):
            return P.export(self.campaign,self.analysis,self.output,exporter_sha256=W.sha(P.__file__),replayer=self.fake_replay)

    def test_complete_compact_bundle_preserves_denominators_clock_and_signal_identity(self):
        target=self.export();record=P.validate_bundle(target)
        self.assertLess(sum(p.stat().st_size for p in target.iterdir()),P.MAX_BUNDLE_BYTES)
        self.assertEqual(record['electronics_replays'],4);self.assertEqual(record['native_drift_calls'],0)
        reps=W.read(target/'representatives.json');self.assertEqual(reps['cs137-left']['group_origin_time_ns'],10000000.)
        self.assertEqual(len(reps['co60-right']['native_reference_channels']),34)
        public=W.read(target/'summary.json');self.assertEqual(public['groups']['co60-right']['transport_denominators']['decay_photons'],17)
        self.assertEqual(public['groups']['gamma-left']['spectrum']['counts'][331],1)
        self.assertNotIn('store_ref',public['inputs'][0]);page=(target/'index.html').read_text()
        for text in ('661.657','1173.228','1332.492','inconclusive','earlier','100 µs','not a recovered distance'):
            self.assertIn(text.lower(),page.lower())
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
        self.assertIn('gegi-campaign/index.html',(out/'index.html').read_text())


if __name__=='__main__':unittest.main()
