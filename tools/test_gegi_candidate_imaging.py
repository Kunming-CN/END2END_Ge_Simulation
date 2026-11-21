"""Synthetic measured stores and one read-only saved context; no native physics."""
from contextlib import closing
import copy
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import gegi_candidate_imaging as A
import gegi_candidate_storage as S


def channels():
    return [{'id': cid, 'family': 'X' if cid <= 17 else 'Y', 'guard': cid in (17,34),
             'strip_center_mm': float((cid-1)%17)*5, 'face_z_mm': 5.5 if cid <= 17 else -5.5}
            for cid in range(1,35)]


def context(trigger_id, sample=80, phase=7.):
    first = sample-30
    return {'kind': 'gegi_exact_sparse_adc_context_v1', 'adc_codes': np.arange(3400,dtype='<i2').reshape(34,100),
        'first_sample_index': first, 'stop_sample_index': first+100, 'adc_phase_ns': phase,
        'sample_period_ns': 20, 'contact_ids': list(range(1,35)), 'volts_per_code': A.digital._LSB_V,
        'digital_profile_sha256': A.digital.PROFILE_SHA256, 'digital_timing_sha256': A.digital.TIMING_SHA256,
        'acquisition_live_samples': 1000, 'readout_trigger_id': trigger_id}


def pairing_card(trigger_id, sample=80):
    return {'trigger_time_ns': sample*20+7., 'energy_keV': 600., 'single_pixel_energy_keV': None,
        'additional_multi_strip_energy_keV': 600., 'x_collecting_strips': [3,11], 'y_collecting_strips': [24,29],
        'guard_contact_ids': [], 'flags': [], 'event_energy_flags': [], 'two_strip_pairings': {
            'flags': [], 'collectors': [], 'pairings': [{'index': 1, 'energy_compatible': True,
                'sites': [{'x_contact_id':3,'y_contact_id':24,'energy_keV':300.},
                          {'x_contact_id':11,'y_contact_id':29,'energy_keV':300.}],
                'compton_orders': [{'site_index_order':[0,1],'kinematically_allowed':True},
                                  {'site_index_order':[1,0],'kinematically_allowed':True}]}]}}


class CandidateImagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(dir=A.W.ROOT/'.local'); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.report = self.root/'candidate-acquisition.json'
        self.database = self.root/S.ARCHIVE_NAME
        request = {'kind':'gegi_campaign_response_request_v1','model_sha256':A.library._ADMITTED_MODEL_SHA256,
            'field_cache':{'model_sha256':A.library._ADMITTED_MODEL_SHA256,'sha256':A.library._ADMITTED_CACHE_SHA256},
            'numerics':{'precision_bits':64,'native_seed':9},'source_sha256':{'preserved_old_producer.py':'f'*64}}
        A.W.write(self.root/'native-request.json',request)
        identity = {'native_request_sha256':A.W.sha(self.root/'native-request.json'),'source_config':{'seed':9},
                    'source_sha256':{'preserved_old_producer.py':'f'*64}}
        source = {'initial_parents':10,'initial_daughter_decays':7}
        self.counts = {'qualified_triggers':5,'qualified_energies':4,'single_pixel_energies':1,
                       'additional_multi_strip_energies':3,'triggers_without_energy':1}
        self.manifest = {'identity':{'model_sha256':request['model_sha256'],'field_cache_sha256':request['field_cache']['sha256'],
            'field_precision_bits':32,'digital_profile_sha256':A.digital.PROFILE_SHA256,'digital_timing_sha256':A.digital.TIMING_SHA256},
            'channels':channels(),'feature_scales':{'fast':1.,'centered_cfd':1.,'pair_cfd':1.}}
        with S.CandidateStore(self.database,identity) as store:
            clean = {'trigger_time_ns':607.,'energy_keV':662.,'single_pixel_energy_keV':662.,
                'x_collecting_strips':[3],'y_collecting_strips':[24],'guard_contact_ids':[],'flags':[],'event_energy_flags':[]}
            store.observe(clean,context(1,30),identities=[10])
            unknown = pairing_card(4,50)
            store.observe(unknown,context(4,50),identities=[20],rejection_reason='unknown_native_history')
            for tid,sample in ((9,80),(12,140)):
                store.observe(pairing_card(tid,sample),context(tid,sample),event={'synthetic_only':tid},identities=[100+tid])
            guard = {**clean,'trigger_time_ns':3607.,'energy_keV':None,'single_pixel_energy_keV':None,
                     'x_collecting_strips':[],'y_collecting_strips':[],'guard_contact_ids':[17]}
            store.observe(guard,context(15,180),identities=[115])
            multiple = {**pairing_card(20,220),'x_collecting_strips':[3,8,11]}
            multiple.pop('two_strip_pairings')
            store.observe(multiple,context(20,220),event={'synthetic_only':20},identities=[120])
            store.save_checkpoint({'channels':channels()})
            completion = store.finalize(acquisition_statistics={'source':source})
        self.document = {'kind':'gegi_candidate_acquisition_v1','status':'completed','identity':identity,'source':source,
            'counts':self.counts,'storage_counts':{key:completion[key] for key in ('observed_coincident_rises','saved_candidates','rejected_rises','selection_reason_counts')},
            'artifacts':{S.ARCHIVE_NAME:{'sha256':A.W.sha(self.database)}},'live_time_ns':20000.,
            'excluded_intervals_ns':[[900.,1200.]],'selection_policy':S.POLICY,
            'verification':{'status':'verified_exact','candidates':3,'ledger_rows':6},
            'readout':{'adc_digest':{'kind':'gegi_fixed_adc_block_chain_v1','chain_sha256':'d'*64}}}
        A.W.write(self.report,self.document)
        self.calibration = self.root/'calibration.npz'; self.calibration.write_bytes(b'synthetic external calibration')

    def loaded(self, path):
        return self.manifest,{(3,24):object(),(11,29):object()},'a'*64,A.W.sha(self.calibration)

    @staticmethod
    def fitted(*args,**kwargs):
        return {'status':'fitted','fits':{'waveform':{'center':{'optimizer_success':True,
                'positions_mm':[[-5.,0.,-1.],[5.,0.,1.]]}}}}

    def run_analysis(self,**kwargs):
        with patch.object(A.calibration,'load',side_effect=self.loaded),patch.object(A,'fit_pairing',side_effect=self.fitted):
            return A.run(self.report,self.calibration,z_mm=40.,extent_mm=40.,step_mm=4.,**kwargs)

    def test_window_uses_original_sample_origin_and_phase_without_baseline_subtraction(self):
        saved={'context':context(9),'trigger_time_ns':1607.}
        volts,status=A.voltage_window(saved,[])
        self.assertEqual(status,'captured');self.assertEqual(volts.shape,(34,29))
        np.testing.assert_array_equal(volts,saved['context']['adc_codes'][:,26:55]*A.digital._LSB_V)
        saved['trigger_time_ns']+=1
        with self.assertRaisesRegex(A.W.ControlError,'ADC clock'):A.voltage_window(saved,[])

    def test_missing_and_excluded_windows_remain_unavailable(self):
        saved={'context':context(9),'trigger_time_ns':1607.}
        self.assertEqual(A.voltage_window(saved,[[1500.,1700.]]),(None,'excluded_history'))
        saved['context']['acquisition_live_samples']=90
        self.assertEqual(A.voltage_window(saved,[]),(None,'outside_live_time'))
        saved['context']['acquisition_live_samples']=1000;saved['context']['first_sample_index']=80
        saved['context']['stop_sample_index']=180
        with self.assertRaisesRegex(A.W.ControlError,'cover'):A.voltage_window(saved,[])

    def test_immutable_store_original_ids_counts_joins_and_ambiguous_orders(self):
        before={p:p.read_bytes() for p in (self.report,self.database,self.root/'native-request.json')}
        result=self.run_analysis()
        self.assertEqual(before,{p:p.read_bytes() for p in before})
        self.assertEqual(result['selection']['qualified_triggers'],5)
        self.assertEqual(result['selection']['qualified_energies'],4)
        self.assertEqual([row['trigger_index'] for row in result['triggers']],[2,3])
        self.assertEqual([row['original_trigger_id'] for row in result['triggers']],[9,12])
        self.assertEqual([row['diagnostic_input_group_ordinals'] for row in result['triggers']],[[109],[112]])
        self.assertEqual(result['layers']['all']['allowed_hypotheses'],4)
        self.assertAlmostEqual(result['layers']['all']['projected_mass'],2.)
        self.assertEqual(result['candidate_analysis']['saved_candidates'],3)
        self.assertEqual(result['candidate_analysis']['retained_candidates_outside_two_strip_scope'],1)
        self.assertEqual(result['candidate_analysis']['storage_counts']['selection_reason_counts']['unknown_native_history'],1)

    def test_explicit_subset_preserves_full_denominator_and_unresolved_mass(self):
        result=self.run_analysis(trigger_ids=[12])
        self.assertEqual(result['candidate_analysis']['scope'],'explicit_analysis_subset')
        self.assertEqual(result['candidate_analysis']['selected_original_trigger_ids'],[12])
        self.assertEqual(result['selection']['qualified_triggers'],5)
        self.assertEqual(result['selection']['two_strip_triggers'],2)
        self.assertAlmostEqual(result['layers']['all']['unresolved_mass'],1.)
        self.assertEqual(result['triggers'][0]['pairings'][0]['waveform_fit_status'],'analysis_subset_not_selected')
        self.assertEqual(self.run_analysis(max_two_strip=1)['candidate_analysis']['selected_original_trigger_ids'],[9])
        with self.assertRaisesRegex(A.W.ControlError,'not an eligible'):self.run_analysis(trigger_ids=[4])

    def test_missing_templates_and_failed_optimizer_are_not_promoted_to_geometry(self):
        for fit in ({'status':'no_center_template_for_pixel'},
                    {'status':'fitted','fits':{'waveform':{'center':{'optimizer_success':False}}}}):
            with self.subTest(fit=fit),patch.object(A.calibration,'load',side_effect=self.loaded),patch.object(A,'fit_pairing',return_value=fit):
                result=A.run(self.report,self.calibration,z_mm=40.,extent_mm=40.)
                self.assertEqual(result['layers']['all']['projected_mass'],0.)
                self.assertEqual(result['layers']['all']['unresolved_mass'],2.)

    def test_exact_cache_precision_and_digital_admission(self):
        request=A.W.read(self.root/'native-request.json')
        self.assertEqual(A._admit_calibration(request,self.manifest,channels())['identity']['field_precision_bits'],32)
        bad=copy.deepcopy(self.manifest);bad['identity']['field_precision_bits']=64
        with self.assertRaises(A.W.ControlError):A._admit_calibration(request,bad,channels())
        bad=copy.deepcopy(request);bad['field_cache']['sha256']='b'*64
        with self.assertRaisesRegex(A.W.ControlError,'not admitted'):A._admit_calibration(bad,self.manifest,channels())

    def test_record_tampering_and_report_count_changes_are_rejected(self):
        changed=copy.deepcopy(self.document);changed['counts']['qualified_triggers']=99
        A.W.write(self.report,changed)
        with self.assertRaisesRegex(A.W.ControlError,'populations'):self.run_analysis()
        A.W.write(self.report,self.document)
        with closing(sqlite3.connect(self.database)) as db,db:db.execute("UPDATE triggers SET record_sha256=? WHERE trigger_id=9",('0'*64,))
        self.document['artifacts'][S.ARCHIVE_NAME]['sha256']=A.W.sha(self.database);A.W.write(self.report,self.document)
        with self.assertRaisesRegex(A.W.ControlError,'record changed'):self.run_analysis()

    def test_saved_completed_candidate_context_is_read_only(self):
        report=A.W.ROOT/'.local/gegi-candidate-runs/steady-five-seconds/candidate-acquisition.json'
        if not report.is_file():self.skipTest('Completed local science is not included in clean clones')
        database=report.parent/S.ARCHIVE_NAME;before=database.stat()
        with closing(S._open_readonly(database)) as db:
            row=db.execute("SELECT trigger_id FROM triggers WHERE decision='candidate' ORDER BY trigger_id LIMIT 1").fetchone()
        saved=S.load_candidate(database,row[0])
        volts,status=A.voltage_window(saved,A.W.read(report)['excluded_intervals_ns'])
        self.assertIn(status,('captured','outside_live_time','excluded_history'))
        if status=='captured':self.assertEqual(volts.shape,(34,29))
        after=database.stat();self.assertEqual((before.st_size,before.st_mtime_ns),(after.st_size,after.st_mtime_ns))


if __name__=='__main__':unittest.main()
