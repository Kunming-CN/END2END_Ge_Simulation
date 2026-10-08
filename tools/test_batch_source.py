"""Shared batch transport contracts with injected legacy readers; no science."""
from contextlib import redirect_stdout
import copy,io,json,sys,unittest
from pathlib import Path
from unittest.mock import Mock,patch
import scenario_workflow as W
import batch_execution as E
import workflow_batches as B
sys.path.insert(0,str(W.ROOT/'transport'))
import batch_source as S

class Source(unittest.TestCase):
    def setUp(self):
        self.selection=dict(name='fixture',cryostat=W.CRYOSTAT,detector='AK01',source=W.CS,pose='nominal',primary_count=25001,seed=42,threads=2,electronics={})
        self.batch=E.batch_at(E.partition(25001,42),2)
    def test_check_cli_consumes_json_data_and_preserves_exact_selection(self):
        out=io.StringIO()
        with patch.object(S,'check',side_effect=lambda value:{'selection':value}),redirect_stdout(out):
            S.main(['check','--request-json',W.encoded(self.selection).decode(),'--windows-root',str(W.ROOT)])
        self.assertTrue(B.typed_equal(json.loads(out.getvalue())['selection'],self.selection))
    def test_catalog_and_original_sources_delegate_bounded_geometry_only(self):
        for detector in (*W.MODELS,'AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'):
            for source in (W.CS,'am241_point_decay_v1','ba133_point_decay_v1'):
                selection=dict(self.selection,detector=detector,source=source)
                with (patch.object(S.C,'check',return_value={'route':'catalog'}) as catalog,patch.object(S.D,'check_request',return_value={'route':'decay'}) as decay,
                    patch.object(S.P,'check',return_value={'route':'legacy'}) as legacy,patch('sap18_source.check_request',return_value={'route':'sap18'}) as sap):
                    S.legacy_check(selection)
                    chosen=catalog if detector not in W.MODELS else decay if source!=W.CS else sap if detector==W.SAP18 else legacy
                    self.assertEqual(chosen.call_count,1);request=chosen.call_args.args[0];self.assertEqual(request['primary_count'],20)
                    self.assertEqual(selection['primary_count'],25001);self.assertEqual(request['seed'],42)
    def test_global_identity_added_raw_local_rows_tracks_times_unchanged(self):
        event=dict(event_id=0,global_decay_id=0,steps=[dict(raw_row_index=41,trackid=3,parent_trackid=1,vertexid=9,time_ns=50200.125,energy_keV=.0001)],
            pulse_groups=[dict(group_id=1,origin_time_ns=50200.125)],particles=[dict(raw_row_index=5,pdg=22)],material_energy_keV={'HPGe':.0001})
        original=copy.deepcopy(event);shared=dict(model_id='AK01',source_mode='cs137_legacy')
        with patch.object(S.C,'events',return_value=iter([event])) as reader:
            row=next(S.raw_events('unused',shared,self.batch))
        self.assertEqual(reader.call_args.args[1]['primary_count'],5001)
        self.assertEqual(row['global_initial_id'],20000);self.assertEqual(row['local_initial_id'],0)
        self.assertTrue(B.typed_equal({key:row[key] for key in original},original))
    def test_literal_macros_change_only_count_and_keep_source_contract(self):
        report={'fixture':True};shared=dict(geometry_report_ref='unused',source_mode='cs137_legacy',source_position_global_mm=[0,37.073,.290])
        with patch.object(S.cs,'load',return_value=report),patch.object(S.P,'safe_path',return_value=Path('unused')),patch.object(S.cs,'macro_text',return_value='/run/beamOn 5001\n') as macro:
            self.assertEqual(S.macro(shared,self.batch),'/run/beamOn 5001\n');self.assertEqual(macro.call_args.args,(report,5001,shared['source_position_global_mm']))
        shared.update(source_mode='registered_decay',source_contract={'isotope':'Am241'})
        with patch.object(S.cs,'load',return_value=report),patch.object(S.P,'safe_path',return_value=Path('unused')),patch.object(S.D,'macro_text',return_value='Am241 literal') as macro:
            S.macro(shared,self.batch);self.assertEqual(macro.call_args.args,(report,5001,shared['source_contract'],shared['source_position_global_mm']))
    def test_invalid_rehashed_ranges_bool_and_unsafe_global_offset_refused(self):
        for key,value in (('primary_count',True),('batch_index',1.),('global_initial_offset',B.MAX_SAFE_INTEGER),('local_initial_primary_id_range',[False,5000]),('global_initial_primary_id_range',[20000,25001])):
            batch=copy.deepcopy(self.batch);batch[key]=value
            with self.subTest(key=key),self.assertRaises((W.ControlError,ValueError)):S.validate_batch(batch)
        S.validate_batch(self.batch)

if __name__=='__main__':unittest.main()
