"""Targeted contracts for the frozen event split and posthoc error accounting."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import numpy as np
import gegi_recovery_validation as V


def view(eid, reason='candidate', stratum='2:2', group=0):
    return {'campaign_initial_id': eid, 'reason': reason, 'stratum': stratum,
            'group_key': [0, eid, group], 'metadata_sha256': str(eid)}


class ValidationTests(unittest.TestCase):
    def test_sample_is_order_independent_and_closes_original_events(self):
        rows = [view(e, stratum='1:2' if e % 2 else '2:2') for e in range(100)]
        rows += [view(e, 'other', group=1) for e in range(10)]
        first = V.select(rows, 5)
        self.assertEqual(first, V.select(list(reversed(rows)), 5))
        V.check_disjoint(first['groups'])
        ids = {a['campaign_initial_id'] for a in first['assignments']}
        self.assertEqual(len(first['groups']), sum(r['campaign_initial_id'] in ids for r in rows))
        for counts in first['targets'].values():
            self.assertLessEqual(max(counts['selected'].values()), 5)

    def test_small_class_halves_and_multiple_groups_cannot_leak(self):
        rows = [view(e) for e in range(5)] + [view(0, 'rare', group=1)]
        selected = V.select(rows)
        self.assertEqual(selected['targets']['candidate']['selected'], {'development': 3, 'holdout': 2})
        event_zero = [g for g in selected['groups'] if g['campaign_initial_id'] == 0]
        self.assertEqual(len(event_zero), 2)
        self.assertEqual(len({g['split'] for g in event_zero}), 1)
        bad = copy.deepcopy(event_zero); bad[1]['split'] = 'holdout' if bad[0]['split'] == 'development' else 'development'
        with self.assertRaisesRegex(ValueError, 'crosses'):
            V.check_disjoint(bad)

    def test_selection_allowlist_ignores_truth_pose_and_energy(self):
        record = {'original_identity': {'campaign_initial_id': 7, 'chunk_index': 0,
                  'raw_primary_id': 7, 'pulse_group_id': 0, 'metadata_sha256': 'abc'},
                  'native_status': 'completed', 'reconstruction': {'reason': 'ambiguous',
                  'candidates': [1], 'strip_counts': [2, 3], 'energy_keV': 99}}
        expected = V.selection_view(record)
        record.update(truth_edep_keV=1000, source_position=[1, 2, 3])
        record['reconstruction']['energy_keV'] = 10000
        record['original_identity']['source_group'] = 'changed'
        self.assertEqual(expected, V.selection_view(record))

    def test_pairing_splitting_residual_and_unknown_are_separate(self):
        h = {'sites': [{'x_contact': 1, 'y_contact': 18, 'position_mm': [0, 0, 1], 'energy_keV': 11},
                       {'x_contact': 2, 'y_contact': 18, 'position_mm': [1, 0, 0], 'energy_keV': 5}]}
        sites = [{'energy': 20, 'processes': {'compt'}}]
        cells = {(1, 18): [10, np.array([0, 0, 0])], (3, 18): [10, np.array([0, 0, 0])]}
        r = V.evaluate_hypothesis(h, sites, 0, cells)
        self.assertFalse(r['endpoint_pairing_matches'])
        self.assertTrue(r['false_gamma_anchor_splitting'])
        self.assertEqual(r['unsupported_predicted_cells'], 1)
        self.assertEqual(r['missing_endpoint_cells'], 1)
        self.assertEqual(r['matched_cell_residuals'][0]['abs_depth_mm'], 1)
        self.assertEqual(r['matched_cell_residuals'][0]['energy_error_keV'], 1)
        unknown = V.evaluate_hypothesis(h, sites, 6, {})
        self.assertIsNone(unknown['endpoint_pairing_matches'])
        self.assertIsNone(unknown['false_gamma_anchor_splitting'])

    def test_sequence_without_timing_is_unknown(self):
        sites = [{'photon_id': 1, 'position': [0, 0, 0], 'processes': {'compt'}, 'x': {1: 5}, 'y': {18: 5}},
                 {'photon_id': 1, 'position': [1, 0, 0], 'processes': {'phot'}, 'x': {2: 5}, 'y': {18: 5}}]
        event = {'input_group': {'parent_event_metadata': {'tracks': [
            {'particle': 11, 'parent_trackid': 1, 'xloc': 0, 'yloc': 0, 'zloc': 0}]}}}
        order, reason = V.sequence_truth(event, sites, 0)
        self.assertIsNone(order)
        self.assertEqual(reason, 'anchor_birth_time_unavailable')

    def test_failed_raw_steps_preserve_truth_anchors_but_endpoints_unknown(self):
        tracks = [{'trackid': 1, 'parent_trackid': 0, 'particle': 22},
                  {'trackid': 2, 'parent_trackid': 1, 'particle': 11,
                   'xloc': 0, 'yloc': 0, 'zloc': 0, 'procid': 4}]
        raw_step = {'track_id': 2, 'particle_pdg': 11, 'energy_keV': 20,
                    'position_mm': [0, 0, 0], 'raw_row_index': 9}
        event = {'status': 'native_failed', 'input_steps': [raw_step],
                 'steps': [raw_step], 'input_group': {'parent_event_metadata': {'tracks': tracks}}}
        original = copy.deepcopy(event)
        result, known = V.posthoc_topology(event, {4: 'compt'})
        self.assertFalse(known)
        self.assertEqual(len(result[0]), 1)
        self.assertEqual(result[0][0]['energy'], 20)
        self.assertEqual(dict(result[6]), {})
        self.assertEqual(event, original)
        # Invalid completed native rows must remain visible, rather than silently
        # being treated like the documented failed/null schema.
        event['status'] = 'completed'
        with self.assertRaises(KeyError):
            V.posthoc_topology(event, {4: 'compt'})

    def test_paired_residuals_match_stable_hypothesis_and_cell_not_population_order(self):
        def residual(cell,depth,energy,position):
            return {'cell':cell,'abs_depth_mm':depth,'abs_energy_error_keV':energy,'position_3d_mm':position}
        def hypothesis(index,pairing,residuals=()):
            return {'hypothesis_index':index,'endpoint_pairing_matches':pairing,'matched_cell_residuals':list(residuals)}
        def row(old,new):
            return {'candidates':[{}] if old else [],'hypotheses':old,
                'candidate_evaluation':{'candidates':[{}] if new else [],'hypotheses':new}}
        old=[hypothesis(7,True,[residual([1,18],4.,1.,5.),residual([2,19],2.,2.,3.)]),
             hypothesis(3,True,[residual([1,18],999.,999.,999.)])]
        new=[hypothesis(9,False,[residual([1,18],777.,777.,777.)]),
             hypothesis(7,True,[residual([2,19],2.,1.,4.),residual([1,18],1.,3.,2.)])]
        rows=[row(old,new),row([], [hypothesis(2,None)]),row([hypothesis(2,False)],[]),row([],[])]
        paired=V.paired_comparison(rows)
        self.assertEqual(paired['candidate_group_transitions'],{'new':1,'retained':1,'lost':1,'no_candidate':1})
        self.assertEqual(paired['candidate_pairing_classes']['baseline'],
            {'all_correct':1,'mixed':0,'all_wrong':1,'none':2,'unknown':0})
        self.assertEqual(paired['candidate_pairing_classes']['candidate'],
            {'all_correct':0,'mixed':1,'all_wrong':0,'none':2,'unknown':1})
        errors=paired['paired_residuals']
        self.assertEqual(errors['shared_conditional_hypotheses'],1)
        self.assertEqual(errors['shared_hypothesis_cells'],2)
        depth=errors['errors']['abs_depth_mm']
        self.assertEqual((depth['baseline']['n'],depth['baseline']['mean']), (2,3.))
        self.assertEqual((depth['candidate']['n'],depth['candidate']['mean']), (2,1.5))
        self.assertEqual((depth['improved'],depth['worse'],depth['tied']), (1,0,1))
        for key in ('abs_energy_error_keV','position_3d_mm'):
            self.assertEqual(tuple(errors['errors'][key][k] for k in ('improved','worse','tied')), (1,1,0))
        self.assertEqual(rows[0]['candidate_pairing_class'],{'baseline':'all_correct','candidate':'mixed'})
        self.assertEqual(rows[1]['candidate_pairing_class']['candidate'],'unknown')


class CandidateValidationTests(unittest.TestCase):
    """Tiny mocked groups exercise the runner, never the numerical fitter."""
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-validation-contract-',dir=V.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        self.campaign=self.root/'campaign';self.reconstruction=self.root/'saved'
        self.calibration=self.root/'calibration';self.calibration.mkdir();self.reconstruction.mkdir()
        V.write_new(self.reconstruction/'COMPLETE.json',{'synthetic':True})
        V.write_new(self.calibration/'identity.json',{'synthetic':True})
        V.write_new(self.root/'COMPLETE.json',{'synthetic_bank_seal':True})
        self.seal=self.campaign/'chunks/g0/b0/DONE.json';self.seal.parent.mkdir(parents=True)
        V.write_new(self.seal,{'synthetic':True})
        process=self.seal.parent/'transport/stream/manifest.json';process.parent.mkdir(parents=True)
        V.write_new(process,{'processes':[]})
        self.spectrum={'accepted':True,'energy_keV':10.,'x_energy_keV':10.,'y_energy_keV':10.,'face_compatible':True}
        self.classification={'spectroscopy':self.spectrum,'supported_imaging':False,
            'terminal_charge_diagnostic':{'mean_keV_equivalent':10.}}
        self.old={'status':'ambiguous','reason':'old_reason','hypotheses':[self.hypothesis(0,1)],
            'candidates':[{'hypothesis_index':0,'order':[0],'prior_weight':1.}], 'unsupported_hypothesis_mass':0.}
        self.new={'status':'ambiguous','reason':'new_reason','fit_calls':3,
            'hypotheses':[self.hypothesis(0,2),{'hypothesis_index':1,'status':'unsupported'},
                          {'hypothesis_index':2,'status':'unsupported'}],
            'candidates':[{'hypothesis_index':0,'order':[0],'prior_weight':1.}], 'unsupported_hypothesis_mass':0.}
        self.groups=[{**view(7,group=0),'metadata_sha256':'7:0','split':'development'},
                     {**view(7,group=1),'metadata_sha256':'7:1','split':'development'},
                     {**view(8,group=0),'metadata_sha256':'8:0','split':'holdout'}]
        self.frozen=self.root/'frozen.json'
        self.manifest={'reconstruction_complete_sha256':V.sha(self.reconstruction/'COMPLETE.json'),
            'groups':self.groups,'assignments':[{'campaign_initial_id':7,'split':'development'},
                                             {'campaign_initial_id':8,'split':'holdout'}]}
        V.write_new(self.frozen,self.manifest)
        self.saved=[{'original_identity':{'chunk_index':0,'raw_primary_id':g['group_key'][1],
            'pulse_group_id':g['group_key'][2],'campaign_initial_id':g['campaign_initial_id'],
            'metadata_sha256':g['metadata_sha256']},'native_status':'completed','reconstruction':self.old}
            for g in self.groups]
        self.channels=[{'id':1,'wiring_factor':1},{'id':18,'wiring_factor':-1}]
        self.done={'response':{'readout_recipe':{'channels':self.channels}},
            'artifacts':{'events.sqlite':{'sha256':'synthetic-store'}}}
        self.bank=type('Bank',(),{'root':self.calibration,'sha256':'synthetic-table',
            'bindings':{'identity.json':V.sha(self.calibration/'identity.json'),
                        '../COMPLETE.json':V.sha(self.root/'COMPLETE.json')}})()
        self.trace=[]

    @staticmethod
    def hypothesis(index,x):
        return {'hypothesis_index':index,'sites':[{'x_contact':x,'y_contact':18,
            'position_mm':[0.,0.,1.],'energy_keV':10.}]}

    def run_fixture(self, output, *, candidate=True, corrupt_spectrum=False):
        import gegi_signal_reconstruction as R
        import gegi_signal_recovery as C
        import gegi_calibration_admission as A
        self.trace=[]
        def saved_group(path,pid,gid):
            return {'event_id':pid,'group_id':gid,'campaign_initial_offset':0,'status':'completed',
                'readout_summary':copy.deepcopy(self.spectrum),'truth_secret':[999,999,999],
                'input_steps':[{'energy_keV':10.}], 'channels':[{'contact_id':1},{'contact_id':18}]}, {}, f'{pid}:{gid}'
        def fit(observed,bank):
            self.assertIs(bank,self.bank)
            self.assertEqual(set(observed),{'event_id','pulse_group_id','status','channels','native'})
            self.assertNotIn('truth_secret',observed)
            self.trace.append(('fit',observed['event_id'],observed['pulse_group_id']))
            return copy.deepcopy(self.new)
        def classify(observed,reconstruction):
            result=copy.deepcopy(self.classification)
            if corrupt_spectrum and reconstruction.get('fit_calls') is not None:
                result['spectroscopy']['energy_keV']=11.
            return result
        def truth(event,names):
            if candidate:
                self.assertEqual(self.trace[-1],('fit',event['event_id'],event['group_id']))
            self.trace.append(('truth',event['event_id'],event['group_id']))
            cells={(1,18):(10.,np.array([0.,0.,0.]))}
            return ([{'energy':10.,'processes':{'compt'}}],[],False,False,False,0.,cells,1),True
        with patch.object(V,'records',side_effect=lambda p:iter(copy.deepcopy(self.saved))), \
             patch('gegi_saved_reconstruction.sealed_chunks',return_value=({},[(0,self.seal,self.done)])), \
             patch.object(R,'read_saved_group',side_effect=saved_group) as reader, \
             patch.object(R,'TemplateBank',return_value=self.bank) as constructor, \
             patch.object(R,'reconstruct_observables',side_effect=fit) as reconstructor, \
             patch.object(A,'campaign',return_value={'status':'compatible_saved_response_identity'}) as admission, \
             patch.object(C,'classify_observables',side_effect=classify), \
             patch.object(V,'posthoc_topology',side_effect=truth), \
             patch.object(V,'sequence_truth',return_value=(None,'synthetic_unknown')):
            kwargs={'frozen_manifest':self.frozen,'split':'development','calibration':self.calibration,
                    'response_mode':'all34'} if candidate else {}
            report=V.evaluate(self.campaign,self.reconstruction,output,**kwargs)
            if candidate:
                constructor.assert_called_once_with(self.calibration,response_mode='all34')
                admission.assert_called_once_with(self.campaign,self.calibration)
                self.assertEqual(reconstructor.call_count,2)
                self.assertEqual([c.args[1:] for c in reader.call_args_list],[(7,0),(7,1)])
            else:
                constructor.assert_not_called();admission.assert_not_called();reconstructor.assert_not_called()
            return report

    def test_single_frozen_split_fits_before_truth_and_saves_paired_metrics(self):
        output=self.root/'candidate-development'
        report=self.run_fixture(output)
        self.assertEqual(report['counts'],{'groups':2,'events':1})
        self.assertEqual(report['new_fit_calls'],6)
        self.assertEqual(report['stage'],'candidate_evaluation_completed')
        self.assertEqual(self.trace,[('fit',7,0),('truth',7,0),('fit',7,1),('truth',7,1)])
        self.assertEqual(report['comparison']['baseline']['conditional_hypothesis_counts']['pairing_matches'],2)
        self.assertEqual(report['comparison']['candidate']['conditional_hypothesis_counts']['pairing_mismatches'],2)
        self.assertEqual(report['comparison']['reason_transitions'],{'old_reason -> new_reason':2})
        self.assertEqual(report['comparison']['candidate_group_transitions'],{'new':0,'retained':2,'lost':0,'no_candidate':0})
        self.assertEqual(report['comparison']['candidate_pairing_classes']['baseline']['all_correct'],2)
        self.assertEqual(report['comparison']['candidate_pairing_classes']['candidate']['all_wrong'],2)
        self.assertEqual(report['comparison']['paired_residuals']['shared_conditional_hypotheses'],2)
        self.assertEqual(report['comparison']['paired_residuals']['shared_hypothesis_cells'],0)
        self.assertEqual(report['comparison']['paired_residuals']['errors']['abs_depth_mm']['baseline'],{'n':0})
        saved=V.read(output/'evaluation-groups.json')
        self.assertEqual(saved['selection'],{'split':'development','groups':self.groups[:2]})
        self.assertTrue(all(row['candidate_reconstruction']==self.new for row in saved['groups']))
        self.assertTrue(all(row['candidate_pairing_class']=={'baseline':'all_correct','candidate':'all_wrong'} for row in saved['groups']))
        self.assertIn('../COMPLETE.json',report['calibration_bindings'])
        before=(output/'report.json').read_bytes()
        with self.assertRaises(FileExistsError):
            V.evaluate(self.campaign,self.reconstruction,output,frozen_manifest=self.frozen,
                       split='development',calibration=self.calibration,response_mode='all34')
        self.assertEqual((output/'report.json').read_bytes(),before)

    def test_default_remains_posthoc_without_bank_or_new_fits(self):
        output=self.root/'legacy';output.mkdir();V.write_new(output/'split-manifest.json',self.manifest)
        report=self.run_fixture(output,candidate=False)
        self.assertEqual(report['stage'],'posthoc_evaluation_completed')
        self.assertEqual(report['new_fit_calls'],0)
        self.assertEqual(report['counts'],{'groups':3,'events':2})
        self.assertNotIn('comparison',report)
        self.assertNotIn('selection',V.read(output/'evaluation-groups.json'))

    def test_candidate_spectroscopy_change_aborts_before_truth(self):
        output=self.root/'bad-candidate'
        with self.assertRaisesRegex(ValueError,'original fixed spectroscopy'):
            self.run_fixture(output,corrupt_spectrum=True)
        self.assertEqual(self.trace,[('fit',7,0)])
        self.assertFalse((output/'report.json').exists())


if __name__ == '__main__':
    unittest.main()
