"""Saved-only publication integrity and truthful zero-map contracts."""
import copy
import gzip
import hashlib
import json
import math
import shutil
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image
import gegi_saved_publication as P


def put(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(P.encoded(value))
    return P.sha(path)


class SavedPublicationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=P.ROOT/'.local')
        self.root = Path(self.tmp.name)
        self.rec, self.image, self.control, self.old = [self.root/n for n in ('reconstruction','imaging','control','old')]
        self.old.mkdir()
        self.input_sha = 'a'*64
        channels = [{'contact_id':i} for i in range(1,35)]
        journey = {'groups':{str(i):{'representative':{'channels':channels},
            'truth_position_mm_for_evaluation_only':[100,0,40]} for i in range(4)}}
        oldhtml = '<script type="application/json" id="gegi-journey-data">'+json.dumps(journey)+'</script>'
        (self.old/'index.html').write_text(oldhtml,encoding='utf-8')
        for name in ('representatives.json','configuration.json','source-assessment.json'):
            put(self.old/name, {'kind':'unchanged_public_fixture'})
        Image.new('RGB',(40,30),'navy').save(self.old/'spectra.png')
        previous = {'status':'complete','route':P.ROUTE,'input_sha256':{'campaign_complete_sha256':'b'*64,'cones.jsonl_sha256':self.input_sha},
                    'artifacts':{p.name:{'bytes':p.stat().st_size,'sha256':P.sha(p)} for p in self.old.iterdir()}}
        previous_sha=put(self.old/'publication.json',previous)
        self.previous_patch=patch.object(P,'PREVIOUS_MANIFEST',previous_sha);self.previous_patch.start()
        counts={'pulse_groups':57613,'conditional_candidate_groups':0,'conditional_candidates':0,'validated_recovered_groups':0}
        self.summary={'kind':'gegi_saved_reconstruction_v3','status':'completed_conditional_reconstruction',
            'campaign_complete_sha256':'b'*64,'counts':counts,'reasons':{'same_pixel_multiplicity_unidentifiable':57613},
            'original_initial_denominators':{str(i):{'initial_primaries':250000} for i in range(4)},
            'source_sha256':{},'limitations':['Selected X/Y templates only; full34channelresponse unavailable.'],
            'new_radiation_calls':0,'new_native_calls':0,'new_field_calls':0,'new_calibration_calls':0}
        summary_sha=put(self.rec/'summary.json',self.summary);identity_sha=put(self.rec/'identity.json',{})
        chunks=[];bindings={'summary.json':summary_sha,'identity.json':identity_sha}
        for i in range(100):
            n=576 if i<99 else 589
            record={'sha256':'c'*64,'source_sha256':{},'counts':{**counts,'pulse_groups':n},
                    'reasons':{'same_pixel_multiplicity_unidentifiable':n}}
            rname=f'chunks/{i:03d}.json';dname=f'chunks/{i:03d}.jsonl.gz'
            h=put(self.rec/rname,record);bindings[rname]=h;bindings[dname]='c'*64
            chunks.append({'chunk_index':i,'receipt_sha256':h,'data_sha256':'c'*64})
        self.complete={'kind':self.summary['kind'],'status':self.summary['status'],'summary_sha256':summary_sha,
                       'identity_sha256':identity_sha,'chunks':chunks}
        bindings['COMPLETE.json']=put(self.rec/'COMPLETE.json',self.complete)
        self.new={'kind':'gegi_joint_conditional_imaging_v3','group_count':0,'source_mass':None,'source_distance_mm':None,
            'activity_bq':None,'provenance':{'truth_used_for_reconstruction':False},
            'saved_signal_accounting':{'input_sha256':bindings,'counts':{'nonzero_pulse_groups':57613,
                'groups_with_conditional_candidates':0,'selected_conditional_groups':0}}}
        put(self.image/'report.json',self.new)
        self.legacy={'kind':'gegi_joint_conditional_imaging_v3','group_count':708,
            'grid':{'x_mm':[-1.,1.],'y_mm':[-1.,1.],'assumed_z_mm':40.,'step_mm':2.,'extent_mm':2.},
            'source_mass':[[.1,.2],[.3,.1]],'angular_backprojection_per_rad':[[1.,2.],[3.,1.]],
            'source_distance_mm':None,'activity_bq':None,'background_fraction':.3,
            'field_of_view_overlap_max_absolute_response_difference':0.,
            'provenance':{'truth_used_for_reconstruction':False,'input_sha256':self.input_sha}}
        put(self.control/'report.json',self.legacy)

    def tearDown(self):
        self.previous_patch.stop(); self.tmp.cleanup()

    def export(self, **kwargs):
        return P.export_saved(self.rec,self.image,self.control,self.old,self.root/'export',**kwargs)

    def reseal(self):
        self.complete['summary_sha256']=put(self.rec/'summary.json',self.summary)
        complete_sha=put(self.rec/'COMPLETE.json',self.complete)
        self.new['saved_signal_accounting']['input_sha256'].update({'summary.json':self.complete['summary_sha256'],'COMPLETE.json':complete_sha})
        put(self.image/'report.json',self.new)

    def test_zero_new_candidates_has_no_fake_map_and_control_is_separate(self):
        manifest=self.export();target=self.root/'export/public'
        self.assertFalse((target/'map-new-pooled.png').exists())
        page=(target/'index.html').read_text(encoding='utf-8')
        self.assertIn('No supported new pooled map',page)
        self.assertIn('Separate control',page)
        self.assertIn('not new recovered events',page)
        self.assertNotIn('truth_position_mm_for_evaluation_only',page)
        self.assertTrue((target/'map-legacy-control.png').exists())
        self.assertEqual(P.validate_public(target),manifest)
        self.assertEqual(manifest['radiation_calls'],0)
        self.assertEqual(manifest['electronics_replays'],0)
        with patch.object(P,'MAX_BUNDLE_BYTES',1), self.assertRaisesRegex(ValueError,'exceeds 1 bytes'):
            P.validate_public(target)

    def test_supported_saved_candidates_render_dynamic_new_map(self):
        self.summary['counts'].update(conditional_candidate_groups=3,conditional_candidates=5)
        receipt=P.read(self.rec/'chunks/000.json')
        receipt['counts'].update(conditional_candidate_groups=3,conditional_candidates=5)
        rh=put(self.rec/'chunks/000.json',receipt)
        self.complete['chunks'][0]['receipt_sha256']=rh
        self.new['saved_signal_accounting']['input_sha256']['chunks/000.json']=rh
        self.new['saved_signal_accounting']['counts'].update(groups_with_conditional_candidates=3,selected_conditional_groups=2,selected_candidates=4)
        self.new.update({k:copy.deepcopy(self.legacy[k]) for k in ('grid','source_mass','angular_backprojection_per_rad')})
        self.new['group_count']=2
        self.new['provenance']['source_sha256']='e'*64
        self.reseal()
        diagnostics=self.image/'event_diagnostics.jsonl'; diagnostics.write_text('{}\n{}\n')
        evaluation={'kind':'gegi_joint_signal_posthoc_truth_evaluation_v1','scope':'Posthoc fixture evaluation',
            'bindings':{'imaging_report_sha256':P.sha(self.image/'report.json'),
                'saved_signal_complete_sha256':P.sha(self.rec/'COMPLETE.json'),
                'imaging_event_diagnostics_sha256':P.sha(diagnostics),'imaging_source_sha256':'e'*64},
            'selection_unchanged':True,'truth_used_in_imaging':False,'group_count':2,'candidate_count':4,
            'selected_ids':[[1,0],[2,0]],'selected_id_census_sha256':'f'*64,'weighting':'unchanged',
            'residual_definition':'signed cone residual','groups':{},
            'pooled':{'finite_vertex':{'unresolved_mass':.5,'candidate_conditional_absolute_residual_quantiles_deg':{'0.5':22.162},
                'angular_compatibility':{'within_15_deg':{'fraction_of_all_selected_group_mass_lower':.3322}}}},
            'energy_layers':{'661.657_keV':{'selected_groups':2,'blind_peaks':[],'acquisition_counts_for_evaluation_only':{},
                'truth_comparison_after_imaging':[{'truth_position_mm_for_evaluation_only':[40,0,40],
                    'has_mode_within_predeclared_15mm':False}]}},
            'distance_mm':None,'activity_bq':None,'range_identified':False,'interpretation':['No validated localization.']}
        put(self.image/'evaluation.json',evaluation)
        manifest=self.export()
        self.assertIn('map-new-pooled.png',manifest['artifacts'])
        summary=P.read(self.root/'export/public/summary.json')
        self.assertEqual(summary['selected_conditional_imaging_groups'],2)
        self.assertEqual(summary['counts']['conditional_candidate_groups'],3)
        self.assertEqual(summary['validated_recovered_groups'],0)
        page=(self.root/'export/public/index.html').read_text(encoding='utf-8')
        self.assertIn('Same-energy source separation still fails.',page)
        self.assertIn('22.162',page)
        self.assertIn('33.22%',page)
        self.assertIn('different populations',page)
        self.assertIn('posthoc_evaluation_sha256',manifest['input_sha256'])

    def test_public_private_path_rejected(self):
        self.summary['limitations'].append('C:/Users/private/account')
        self.reseal()
        with self.assertRaisesRegex(ValueError,'Private path'):
            self.export()

    def test_cone_plane_geometry_and_asymptote_clipping(self):
        import numpy as np
        cone={'axis':[0.,0.,1.], 'vertex_mm':[0.,0.,0.],
            'half_angle_deg':30., 'cos_theta':math.cos(math.radians(30))}
        paths,residual=P._cone_paths(cone,40.,30.)
        self.assertEqual(len(paths),1)
        self.assertLess(residual,1e-12)
        self.assertTrue(np.allclose(np.linalg.norm(paths[0],axis=1),40*math.tan(math.radians(30)),atol=1e-10))
        clipped=P._clipped_paths(np.array([[-2.,0.],[0.,0.],[99.,99.],[0.,1.],[2.,1.]]),
            np.array([True,True,False,True,True]),1.)
        self.assertEqual(len(clipped),2)
        self.assertTrue(all(np.max(np.abs(p))<=1 for p in clipped))
        with self.assertRaisesRegex(ValueError,'saved cone geometry'):
            P._cone_paths({**cone,'cos_theta':0.},40.,30.)

    def test_explicit_population_selection_is_hash_bound(self):
        population=self.root/'population';population.mkdir()
        records=[{'campaign_initial_id':i,'pulse_group_id':0,'energy_keV':662.,
            'candidates':[{'order':[0,1],'prior_weight':.25}]*(1 if i<19 else 2)} for i in range(153)]
        path=self.root/'selected.jsonl.gz'
        with gzip.open(path,'wb') as stream:
            for row in records:stream.write(P.encoded(row)+b'\n')
        diagnostics=self.image/'event_diagnostics.jsonl'
        diagnostics.write_bytes(b''.join(P.encoded({'event_id':r['campaign_initial_id'],
            'pulse_group_id':0,'candidate_count':len(r['candidates'])})+b'\n' for r in records))
        identity=put(population/'identity.json',{})
        image={**self.new,'group_count':153,'provenance':{'map_input_sha256':P.sha(path),
            'population_identity_sha256':identity}}
        image_sha=put(self.image/'report.json',image)
        report={'kind':'gegi_order_prior_population_v1','input_sha256':{
            'reconstruction_complete':P.sha(self.rec/'COMPLETE.json'),'map_records':P.sha(path),
            'old_map_records':'d'*64},'artifact_sha256':{'imaging/report.json':image_sha,
            'imaging/event_diagnostics.jsonl':P.sha(diagnostics)},
            'verification':{'map153_287_matches_population_exactly':True,'all434_nonweight_records_exactly_equal':True}}
        digest=put(population/'result.json',report)
        put(population/'COMPLETE.json',{'status':'completed_sparse_population_and_one_map',
            'result_sha256':digest,'identity_sha256':identity})
        result=P._population_inputs(population,path,self.rec,self.image/'report.json',image)
        self.assertEqual(sum(len(r['candidates']) for r in result['records']),287)
        with gzip.open(path,'ab') as stream:stream.write(b'{}\n')
        with self.assertRaisesRegex(ValueError,'selection binding changed'):
            P._population_inputs(population,path,self.rec,self.image/'report.json',image)

    def test_default_small_energy_layer_and_null_angle_evidence_render(self):
        layer={'id':'cone-layer-3','label':'1332.49_keV','title':'1332.49 keV',
            'groups':18,'candidates':36,'visible_candidates':30,
            'files':{'overlay':'overlay.png','density':'density.png','conditional':'conditional.png'}}
        pooled={**layer,'id':'cone-layer-0','label':'pooled','title':'All selected energies','groups':153,'candidates':287}
        display={'default_layer':layer['id'],'plane_z_mm':40.,'em_iterations':40,'layers':[pooled,layer]}
        page=P._render_cone_page({'cone_plane_display':display,'posthoc_evaluation':{'pooled':{'finite_vertex':None}}},
            {'group_count':153},{ }).decode()
        self.assertIn('value="cone-layer-3" selected',page)
        self.assertIn('18 groups · 36 candidate cones',page)
        self.assertIn('Small sample; limited statistics.',page)
        self.assertEqual(page.count('40 iterations'),1)
        self.assertNotIn('truth_position',page)
        page=P._render_cone_page({'cone_plane_display':display}, {'group_count':153},{},
            {'groups':{'saved':{'representative':{'channels':[]}}}}).decode()
        self.assertIn('id="gegi-journey-data"',page)
        self.assertIn('id="historical-journey"',page)
        for anchor in ('new-map','spectra','journey'):
            self.assertIn('<section id="'+anchor+'">',page)
        self.assertIn('<nav class="local">',page)
        self.assertIn('<article class="cone-layer"',page)
        from check_site import Links, resolve_reference
        links=Links();links.feed(page)
        for link in links.urls:
            target=resolve_reference(P.ROUTE,link)
            if target is not None and target['path']==P.ROUTE and target['fragment']:
                self.assertIn(target['fragment'],links.anchors)
        import site_restructure
        target=self.root/'deferred-render';target.mkdir()
        (target/'gegi_signal_journey.js').write_bytes((P.ROOT/'tools/gegi_signal_journey.js').read_bytes())
        deferred=site_restructure.defer_gegi_journey(target,page,{'artifacts':{}})
        self.assertNotIn('id="gegi-journey-data"',deferred)
        self.assertIn("panel.addEventListener('toggle',load)",deferred)

    def all_event_fixture(self):
        self.summary['counts'].update(conditional_candidate_groups=3,conditional_candidates=4)
        receipt=P.read(self.rec/'chunks/000.json');receipt['counts'].update(conditional_candidate_groups=3,conditional_candidates=4)
        self.complete['chunks'][0]['receipt_sha256']=put(self.rec/'chunks/000.json',receipt)
        self.reseal()
        population=self.root/'population';population.mkdir();all_root=self.root/'all-events'
        def candidate(order,weight,index=0):
            return {'order':order,'hypothesis_index':index,'prior_weight':weight,
                'axis':[0.,0.,1.],'vertex_mm':[0.,0.,0.],'half_angle_deg':30.,'cos_theta':math.cos(math.radians(30))}
        records=[{'campaign_initial_id':1,'pulse_group_id':0,'energy_keV':662.,
                    'candidates':[candidate([0,1],.25),candidate([0,1,2],.125,1)]},
                 {'campaign_initial_id':2,'pulse_group_id':0,'energy_keV':1173.228,
                    'candidates':[candidate([0,1,2,3],.1)]},
                 {'campaign_initial_id':3,'pulse_group_id':0,'energy_keV':300.,
                    'candidates':[candidate([0,1],.5)]}]
        all_root.mkdir();path=all_root/'records.jsonl';path.write_bytes(b''.join(P.encoded(r)+b'\n' for r in records))
        subset=[{**records[0],'candidates':records[0]['candidates'][:1]},records[2]]
        subset_path=self.root/'evaluation/map-records.jsonl.gz';subset_path.parent.mkdir()
        with gzip.open(subset_path,'wb') as stream:
            for row in subset:stream.write(P.encoded(row)+b'\n')
        source=P.sha(P.ROOT/'tools/gegi_joint_imaging.py')
        old_image={**copy.deepcopy(self.legacy),'group_count':2,'provenance':{
            'source_sha256':source,'truth_used_for_reconstruction':False}}
        old_image_path=population/'imaging/report.json';old_image_sha=put(old_image_path,old_image)
        old_diagnostics=old_image_path.parent/'event_diagnostics.jsonl'
        old_diagnostics.write_bytes(b''.join(P.encoded({'event_id':r['campaign_initial_id'],
            'pulse_group_id':0,'candidate_count':len(r['candidates'])})+b'\n' for r in subset))
        evaluation={'kind':'gegi_joint_signal_posthoc_truth_evaluation_v1','scope':'Exact fixture subset',
            'bindings':{'imaging_report_sha256':old_image_sha,'saved_signal_complete_sha256':P.sha(self.rec/'COMPLETE.json'),
                'imaging_event_diagnostics_sha256':P.sha(old_diagnostics),'imaging_source_sha256':source},
            'selection_unchanged':True,'truth_used_in_imaging':False,'group_count':2,'candidate_count':2,
            'selected_ids':[[1,0],[3,0]],'selected_id_census_sha256':'f'*64,'weighting':'original prior',
            'residual_definition':'Existing subset only','groups':{},'pooled':{'saved_metric':2.5},
            'energy_layers':{},'distance_mm':None,'activity_bq':None,'range_identified':False,'interpretation':[]}
        eval_path=population/'imaging/evaluation.json';eval_sha=put(eval_path,evaluation)
        self.image=all_root/'imaging'
        image={**copy.deepcopy(self.legacy),'group_count':3,'em_iterations':40,
            'provenance':{'input_sha256':P.sha(path),'source_sha256':source,'truth_used_for_reconstruction':False},
            'spectral_layers':{label:{'group_count':1,'source_mass':self.legacy['source_mass'],
                'angular_backprojection_per_rad':self.legacy['angular_backprojection_per_rad']}
                for label in ('661.657_keV','1173.23_keV','other_energy')}}
        image_sha=put(self.image/'report.json',image)
        diagnostics=self.image/'event_diagnostics.jsonl';diagnostics.write_bytes(b''.join(P.encoded({
            'event_id':r['campaign_initial_id'],'pulse_group_id':0,'candidate_count':len(r['candidates'])})+b'\n' for r in records))
        identity=put(population/'identity.json',{})
        report={'kind':'gegi_order_prior_population_v1','counts':{'all_saved_nonzero_groups':57613,
            'candidate_bearing_groups':3,'candidates':4},'original_saved_reconstruction_counts':self.summary['counts'],
            'input_sha256':{'reconstruction_complete':P.sha(self.rec/'COMPLETE.json'),'map_records':P.sha(subset_path)},
            'artifact_sha256':{'groups.jsonl.gz':'c'*64,'imaging/report.json':old_image_sha,
                'imaging/event_diagnostics.jsonl':P.sha(old_diagnostics)},
            'verification':{'all434_nonweight_records_exactly_equal':True}}
        report_sha=put(population/'result.json',report)
        complete_sha=put(population/'COMPLETE.json',{'status':'completed_sparse_population_and_one_map',
            'result_sha256':report_sha,'identity_sha256':identity})
        census_sha=put(self.root/'selection-census.json',{'kind':'fixture_census'})
        ids=[[1,0],[2,0],[3,0]]
        selected={'kind':'gegi_all_saved_candidates_map_v1','status':'completed','group_count':3,'candidate_count':4,
            'candidate_site_counts':{'2':2,'3':1,'4':1},'selection':{k:False for k in
                ('energy_window_filter','site_count_filter','truth_used','source_labels_used')},
            'all_candidates_and_priors_exactly_preserved':True,'candidate_priors_renormalized':False,
            'candidate_prior_mass':.975,'uninformative_mass':2.025,'selected_ids':ids,
            'selected_ids_sha256':hashlib.sha256(P.encoded(ids)).hexdigest(),
            'selected_candidate_keys_sha256':hashlib.sha256(P.encoded(P._candidate_keys(records))).hexdigest(),
            'spectral_layer_group_counts':{label:1 for label in image['spectral_layers']},
            'bindings':{'parent_population_complete_sha256':complete_sha,'parent_population_result_sha256':report_sha,
                'parent_sparse_records_sha256':'c'*64,'saved_signal_complete_sha256':P.sha(self.rec/'COMPLETE.json'),
                'saved_signal_summary_sha256':P.sha(self.rec/'summary.json'),'selection_census_sha256':census_sha,
                'projected_records_sha256':P.sha(path),'imaging_report_sha256':image_sha,
                'imaging_event_diagnostics_sha256':P.sha(diagnostics),'imaging_source_sha256':source,
                'subset_evaluation_sha256':eval_sha,'subset_imaging_report_sha256':old_image_sha,
                'subset_event_diagnostics_sha256':P.sha(old_diagnostics),'subset_map_records_sha256':P.sha(subset_path)},
            'reused_evaluation_subset':{'group_intersection_count':2,'candidate_key_intersection_count':2,
                'groups_with_all_candidate_keys_in_existing_evaluation':1,
                'groups_with_additional_unevaluated_candidate_keys':1,
                'additional_unevaluated_candidates_in_intersecting_groups':1,
                'groups_without_existing_evaluation':1,'unevaluated_candidate_keys':2,
                'errors_scope':'Two saved keys only.'}}
        selection_path=all_root/'map-selection.json';put(selection_path,selected)
        return population,path,selection_path

    def test_all_event_export_defaults_to_pooled_and_keeps_other_energy_and_subset(self):
        population,path,selection=self.all_event_fixture()
        manifest=self.export(order_prior_population=population,map_records=path,map_selection=selection)
        target=self.root/'export/public';summary=P.read(target/'summary.json')
        display=summary['cone_plane_display'];accuracy=summary['posthoc_evaluation']
        self.assertEqual(display['default_layer'],'cone-layer-0')
        self.assertEqual((display['layers'][0]['groups'],display['layers'][0]['candidates']),(3,4))
        other=next(layer for layer in display['layers'] if layer['label']=='other_energy')
        self.assertEqual(other['title'],'Other readout energies')
        self.assertEqual(other['groups'],1)
        self.assertEqual(accuracy['kind'],'gegi_saved_evaluation_coverage_v1')
        self.assertEqual((accuracy['map_group_count'],accuracy['map_candidate_count']),(3,4))
        self.assertEqual((accuracy['evaluated_subset']['group_count'],accuracy['evaluated_subset']['candidate_count']),(2,2))
        self.assertEqual(accuracy['evaluated_subset']['pooled'],{'saved_metric':2.5})
        self.assertNotIn('pooled',accuracy)
        page=(target/'index.html').read_text(encoding='utf-8')
        self.assertIn('value="cone-layer-0" selected',page)
        self.assertIn('3 groups · 4 candidate cones',page)
        self.assertIn('Saved evaluation subset: 2 groups / 2 candidate orders',page)
        self.assertIn('subset_posthoc_evaluation_sha256',manifest['input_sha256'])
        P.validate_public(target)
        with patch.object(P,'MAX_ALL_EVENT_BUNDLE_BYTES',1), self.assertRaisesRegex(ValueError,'exceeds 1 bytes'):
            P.validate_public(target)

    def test_all_event_selection_rejects_filtering_and_changed_projected_records(self):
        population,path,selection=self.all_event_fixture();selected=P.read(selection)
        selected['selection']['site_count_filter']=True;put(selection,selected)
        with self.assertRaisesRegex(ValueError,'selection contract'):
            P._all_map_inputs(population,path,self.rec,self.image/'report.json',P.read(self.image/'report.json'),selection)
        selected['selection']['site_count_filter']=False;put(selection,selected)
        path.write_bytes(path.read_bytes()+b'{}\n')
        with self.assertRaisesRegex(ValueError,'map-selection binding'):
            P._all_map_inputs(population,path,self.rec,self.image/'report.json',P.read(self.image/'report.json'),selection)

    def test_all_event_evaluation_rejects_incorrect_candidate_coverage(self):
        population,path,selection=self.all_event_fixture()
        migration=P._all_map_inputs(population,path,self.rec,self.image/'report.json',P.read(self.image/'report.json'),selection)
        migration['selection']['reused_evaluation_subset']['additional_unevaluated_candidates_in_intersecting_groups']=0
        with self.assertRaisesRegex(ValueError,'candidate-key coverage'):
            P._evaluation_coverage(population/'imaging/evaluation.json',population,self.rec,migration)

    def test_completed_input_hash_change_rejected(self):
        (self.rec/'summary.json').write_bytes((self.rec/'summary.json').read_bytes()+b' ')
        with self.assertRaisesRegex(ValueError,'completion binding'):
            self.export()

    def test_posthoc_evaluation_cannot_bind_a_different_map(self):
        evaluation={'kind':'gegi_joint_signal_posthoc_truth_evaluation_v1',
            'selection_unchanged':True,'truth_used_in_imaging':False,
            'bindings':{'imaging_report_sha256':'0'*64}}
        path=self.image/'wrong-evaluation.json';put(path,evaluation)
        with self.assertRaisesRegex(ValueError,'evaluation input binding changed'):
            P._evaluation_summary(path,self.image,self.rec,self.new)

    def test_exact_old708_input_required(self):
        self.legacy['provenance']['input_sha256']='d'*64
        put(self.control/'report.json',self.legacy)
        with self.assertRaisesRegex(ValueError,'exact original708|exact original 708'):
            self.export()

    def test_artifact_tamper_fails_validation(self):
        self.export();target=self.root/'export/public'
        (target/'spectra.png').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'artifact hash changed'):
            P.validate_public(target)

    def test_source_pin_tamper_fails_validation(self):
        self.export();target=self.root/'export/public'
        m=P.read(target/'publication.json');m['source_sha256'][P.SOURCE_FILES[0]]='0'*64
        put(target/'publication.json',m)
        with self.assertRaisesRegex(ValueError,'source pins changed|source provenance changed'):
            P.validate_public(target)

    def test_historical_sources_keep_old_bytes_and_census_checked(self):
        self.export(); target=self.root/'export/public'
        changed={**P._source_pins(P.ROOT),P.SOURCE_FILES[0]:'f'*64}
        with patch.object(P,'_source_pins',return_value=changed):
            with self.assertRaisesRegex(ValueError,'source pins changed'):
                P.validate_public(target)
            P.validate_public(target,allow_historical_sources=True)
            (target/'spectra.png').write_bytes(b'tampered historical artifact')
            with self.assertRaisesRegex(ValueError,'artifact hash changed'):
                P.validate_public(target,allow_historical_sources=True)

    def test_explicit_replacement_admits_old_sources_but_requires_current_candidate(self):
        import gegi_campaign_publication as campaign
        self.export(); old=self.root/'export/public'; previous=P.sha(old/'publication.json')
        site=self.root/'site'; installed=site/'results/gegi-campaign'
        shutil.copytree(old,installed)
        changed={**P._source_pins(P.ROOT),P.SOURCE_FILES[0]:'f'*64}
        with patch.object(P,'_source_pins',return_value=changed):
            with self.assertRaisesRegex(ValueError,'source pins changed'):
                campaign.install_bundle(old,site)
            P.export_saved(self.rec,self.image,self.control,self.old,self.root/'replacement',
                           replace_public_manifest_sha256=previous)
            candidate=self.root/'replacement/public'
            campaign.install_bundle(candidate,site)
            record=P.validate_public(installed)
            self.assertEqual(record['source_sha256'],changed)
            self.assertEqual(record['replaces_public_manifest_sha256'],previous)
            self.assertEqual(record['input_sha256']['previous_public_manifest_sha256'],P.PREVIOUS_MANIFEST)
            self.assertEqual((installed/'spectra.png').read_bytes(),(old/'spectra.png').read_bytes())

    def test_incomplete_processing_cannot_be_exported(self):
        self.complete['status']='running_saved_reconstruction';put(self.rec/'COMPLETE.json',self.complete)
        with self.assertRaisesRegex(ValueError,'Only completed'):
            self.export()

    def test_map_uses_actual_values_and_rejects_empty(self):
        path=self.root/'map.png'
        P.map_figure(self.legacy,path,'saved numerical map')
        with Image.open(path) as image:
            self.assertEqual(image.size,(960,720))
            self.assertNotEqual(image.getpixel((200,200)),image.getpixel((600,200)))
        bad={**self.legacy,'source_mass':[[0.,0.],[0.,0.]]}
        with self.assertRaisesRegex(ValueError,'empty map'):
            P.map_figure(bad,self.root/'bad.png','invalid')

    def test_no_unrequested_science_reader_imports(self):
        source=Path(P.__file__).read_text(encoding='utf-8')
        self.assertNotIn('import gegi_campaign_analysis',source)
        self.assertNotIn('import gegi_signal_reconstruction',source)
        self.assertNotIn('sqlite3',source)
        self.assertNotIn('subprocess',source)

    def recovery_fixture(self):
        root = self.root/'recovery'; inputs = {'reconstruction_complete_sha256':P.sha(self.rec/'COMPLETE.json'),
            'reconstruction_summary_sha256':P.sha(self.rec/'summary.json'),
            'joint_imaging_report_sha256':P.sha(self.image/'report.json')}
        assignments = [{'campaign_initial_id':i,'split':'development' if i<200 else 'holdout'} for i in range(400)]
        split = {'kind':'gegi_saved_recovery_validation_v1','stage':'frozen_before_truth_evaluation',
            'reconstruction_complete_sha256':inputs['reconstruction_complete_sha256'],
            'reconstruction_summary_sha256':inputs['reconstruction_summary_sha256'],
            'selection_truth_used':False,'selection_source_labels_used':False,
            'counts':{'events':400,'groups':400,'groups_by_split':{'development':200,'holdout':200}},
            'assignments':assignments,'groups':assignments}
        split_sha = put(root/'validation/split-manifest.json',split)
        groups_sha = put(root/'validation/evaluation-groups.json',{'split_manifest_sha256':split_sha,'groups':[{}]*400})
        report = {'kind':split['kind'],'stage':'posthoc_evaluation_completed','counts':{'events':400,'groups':400},
            'new_calibration_calls':0,'new_fit_calls':0,'new_physics_calls':0,
            'split_manifest_sha256':split_sha,'evaluation_groups_sha256':groups_sha,'by_split':{}}
        for name,n,m,f,c,w,u,cells in (('development',22,3,1,2,2,40,49),('holdout',24,5,2,2,6,40,50)):
            report['by_split'][name] = {'counts':{'groups':200,'original_spectroscopy_exact_match_groups':200,
                'classified_imaging_supported_groups':0},'conditional_hypothesis_counts':{'conditional_hypotheses':n,
                'pairing_mismatches':m,'pairing_known':n,'false_splitting':f,'splitting_known':n},
                'sequence':{'correct':c,'wrong':w,'unknown':u},'errors':{'abs_depth_mm':{'n':cells,'median':.1,'p90':.4,'max':2.}}}
        report_sha = put(root/'validation/report.json',report)
        identity = {'kind':'gegi_saved_signal_use_v1','campaign_complete_sha256':self.summary['campaign_complete_sha256'],
            'reconstruction_complete_sha256':inputs['reconstruction_complete_sha256'],
            'reconstruction_summary_sha256':inputs['reconstruction_summary_sha256']}
        counts = {'pulse_groups':57613,'conditional_candidate_groups':0,'spectroscopy_groups':50000,
            'guard_collection_groups':100,'guard_transient_groups':200,'adjacent_strip_groups':300,'native_failed_groups':426}
        use = {**identity,'status':'completed_signal_use_classification','counts':counts,
            'categories':{'spectroscopy_only':50000,'ambiguous_imaging':0,'failed_or_incomplete':1896,'unresolved_signal':5717},
            'new_calibration_calls':0,'new_field_calls':0,'new_native_calls':0,'new_radiation_calls':0,
            'repeated_waveform_fits':0,'new_energy_reconstructions':0,'new_validated_imaging_recoveries':0,
            'spectroscopy_matches_original_readout':True}
        put(root/'signal-use-v2/COMPLETE.json',{'kind':identity['kind'],'status':use['status'],
            'summary_sha256':put(root/'signal-use-v2/summary.json',use),
            'identity_sha256':put(root/'signal-use-v2/identity.json',identity),
            'chunks':[{'chunk_index':i,'counts':counts if i==0 else {}} for i in range(100)]})
        put(self.rec/'identity.json',{'calibration_sha256':'c'*64})
        manifest = root/'calibration/inputs.jsonl'
        put(manifest,{'ref':'.local/gegi-10m/pixel-calibration/depth-calibration.json','sha256':'c'*64})
        put(root/'calibration/inventory.json',{'status':'complete_full34_responses_absent',
            'counts':{'injection_records':2991,'full34_records':0,'records_by_stored_channel_count':{'2':2727,'0':264}},
            'input_manifest':{'sha256':P.sha(manifest)},'saved_drift_trajectories':{'present':False}})
        peaks = [{'position_mm':[38.,-2.,40.],'on_image_edge':False},{'position_mm':[46.,18.,40.],'on_image_edge':False}]
        peak = {'kind':'gegi_saved_peak_diagnostic_v1','group_count':19,'candidate_count':58,'selected_original_ids':list(range(19)),
            'energy_center_keV':1332.492,'grid':{'assumed_z_mm':40.,'step_mm':4.,'extent_mm':120.},
            'baseline':{'blind_peaks':peaks},'grid_iteration_sensitivity':[{}]*12,
            'leave_one_group_out_summary':[{'position_mm':p['position_mm'],'omissions_with_displayed_mode_within_8_mm':n,
                'nearest_displayed_mode_distance_mm_min_max':[0.,22.]} for p,n in zip(peaks,(19,16))],
            'provenance':{'baseline_report_sha256':inputs['joint_imaging_report_sha256'],
                'saved_input_sha256':{'COMPLETE.json':inputs['reconstruction_complete_sha256'],
                    'summary.json':inputs['reconstruction_summary_sha256']},
                'truth_used':False,'source_labels_used':False,'new_transport_drift_fields_or_calibration':0}}
        put(root/'peak-diagnostic/COMPLETE.json',{'files':{'report.json':put(root/'peak-diagnostic/report.json',peak)}})
        circuit = {'channels_checked':34,'all_ADC_codes_equal':True,'all_fixed_energy_gains_equal':True,'max_peak_absolute_error_V':1e-13}
        evidence = {'kind':'gegi_frozen_development_saved_readout_diagnosis_v1','evaluation_report_sha256':report_sha,
            'split_manifest_sha256':split_sha,'evaluation_groups_sha256':groups_sha,
            'new_calibration_calls':0,'new_fit_calls':0,'new_native_calls':0,'new_transport_calls':0,
            'selected_groups':[{'split':'development','independent_circuit_check':circuit,'endpoint_status_counts':{'contact':86}}]*3,
            'findings':[{'evidence':{'mean_ADC_minus_terminal_keV':12.745,'X_strip_9_terminal_keV':15.511,
                'X_strip_9_charge_transient_max_keV':271.113,'X_strip_9_analog_peak_energy_keV':43.381}}, {},
                {'evidence':{'mean_native_terminal_deficit_keV':-45.904,'deposition_keV':1094.729}}]}
        guard_identity = {'campaign_initial_id':723606,'metadata_sha256':'d'*64}
        evidence['selected_groups'][2]['original_identity'] = guard_identity
        endpoint = {'kind':'gegi_saved_endpoint_weight_result_v1','original_identity':{'campaign_initial_id':723606},
            'original_bindings':{'metadata_sha256':'d'*64},'native_precision_bits':32,'max_abs_prediction_error_keV':0.0,
            'new_calibration_calls':0,'new_drift_calls':0,'new_field_solves':0}
        evidence['saved_field_endpoint_diagnosis'] = {'endpoint_result_sha256':put(root/'validation/endpoint-weights.json',endpoint),
            'acceptance':{'all_contact_mappings_identical':True,'contact_endpoint_mappings_compared':86,
                'saved_native_terminal_values_compared':34,'max_abs_prediction_error_keV':0.0,
                'new_drift_calls':0,'new_field_solves':0,'new_injection_calls':0},
            'bounds':{'electron_guard34_own_phi_min':.90593,'electron_guard34_own_phi_max':.94087,
                'hole_guard17_own_phi_min':.96870,'hole_guard17_own_phi_max':1.0}}
        put(root/'validation/readout-diagnosis.json',evidence)
        image = {**self.new,'spectral_layers':{'1332.49_keV':{'group_count':19}}}
        return root, inputs, image

    def test_recovery_aggregates_exclude_private_rows_and_keep_unknowns(self):
        root, inputs, image = self.recovery_fixture()
        report=P.read(root/'validation/report.json');report['private_notes']='C:/Users/private/account'
        digest=put(root/'validation/report.json',report)
        diagnosis=P.read(root/'validation/readout-diagnosis.json');diagnosis['evaluation_report_sha256']=digest
        diagnosis['findings'][0]['diagnosis']='C:/Users/private/source';put(root/'validation/readout-diagnosis.json',diagnosis)
        recovery, bindings=P._recovery_summary(root,self.rec,image,self.summary,inputs)
        P.public(P.encoded(recovery))
        self.assertEqual(recovery['frozen_stratified_sample']['holdout']['sequence_candidates']['unknown'],40)
        page=P._recovery_html(recovery)
        self.assertIn('3/22',page);self.assertIn('5/24',page)
        self.assertIn('2 / 6 / 40',page);self.assertIn('271.113',page)
        self.assertIn('reproduces all 34 saved terminal values with exactly 0.0 keV error',page)
        self.assertIn('A waveform correction remains unvalidated',page)
        self.assertNotIn('cause is not yet established',page)
        self.assertNotIn('C:/Users',page)
        self.assertEqual(len(bindings),12)

    def test_recovery_endpoint_diagnosis_changed_result_refused(self):
        root, inputs, image=self.recovery_fixture()
        path=root/'validation/endpoint-weights.json';endpoint=P.read(path)
        endpoint['max_abs_prediction_error_keV']=1.0;put(path,endpoint)
        with self.assertRaisesRegex(ValueError,'endpoint diagnosis identity'):
            P._recovery_summary(root,self.rec,image,self.summary,inputs)

    def test_recovery_different_campaign_and_repeated_fits_refused(self):
        root, inputs, image=self.recovery_fixture()
        path=root/'signal-use-v2/summary.json';use=P.read(path);use['campaign_complete_sha256']='x'*64
        seal=P.read(root/'signal-use-v2/COMPLETE.json');seal['summary_sha256']=put(path,use)
        put(root/'signal-use-v2/COMPLETE.json',seal)
        with self.assertRaisesRegex(ValueError,'different campaign'):
            P._recovery_summary(root,self.rec,image,self.summary,inputs)
        use['campaign_complete_sha256']=self.summary['campaign_complete_sha256'];use['repeated_waveform_fits']=1
        seal['summary_sha256']=put(path,use);put(root/'signal-use-v2/COMPLETE.json',seal)
        with self.assertRaisesRegex(ValueError,'altered saved reconstruction'):
            P._recovery_summary(root,self.rec,image,self.summary,inputs)

    def test_recovery_split_overlap_and_wrong_census_refused(self):
        root, inputs, image=self.recovery_fixture();path=root/'validation/split-manifest.json';split=P.read(path)
        split['assignments'][1]['campaign_initial_id']=0
        split_sha=put(path,split)
        report=P.read(root/'validation/report.json');report['split_manifest_sha256']=split_sha
        groups=P.read(root/'validation/evaluation-groups.json');groups['split_manifest_sha256']=split_sha
        report['evaluation_groups_sha256']=put(root/'validation/evaluation-groups.json',groups)
        put(root/'validation/report.json',report)
        with self.assertRaisesRegex(ValueError,'split leaks or duplicates'):
            P._recovery_summary(root,self.rec,image,self.summary,inputs)

    def test_optional_recovery_artifact_is_bound_in_public_bundle(self):
        evidence={'kind':'gegi_public_saved_recovery_evidence_v1'}
        with patch.object(P,'_recovery_summary',return_value=(evidence,{})), patch.object(P,'_recovery_html',return_value='<p>Saved evidence</p>'):
            result=self.export(recovery_evidence=self.root/'recovery')
        target=self.root/'export/public'
        self.assertEqual(P.read(target/'recovery-summary.json'),evidence)
        self.assertIn('saved_recovery_evidence_sha256',result['input_sha256'])
        self.assertNotIn('map-new-pooled.png',result['artifacts'])
        (target/'recovery-summary.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'artifact hash changed'):
            P.validate_public(target)


if __name__=='__main__':
    unittest.main()
