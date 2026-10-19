"""Saved-only publication integrity and truthful zero-map contracts."""
import copy
import hashlib
import json
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
        with self.assertRaisesRegex(ValueError,'source pins changed'):
            P.validate_public(target)

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
        source=Path(P.__file__).read_text()
        self.assertNotIn('import gegi_campaign_analysis',source)
        self.assertNotIn('import gegi_signal_reconstruction',source)
        self.assertNotIn('sqlite3',source)
        self.assertNotIn('subprocess',source)


if __name__=='__main__':
    unittest.main()
