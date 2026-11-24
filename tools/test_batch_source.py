"""Shared batch transport contracts with injected legacy readers; no science."""
from contextlib import redirect_stdout
import copy,io,json,sys,tempfile,types,unittest
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
    def test_angle_selection_preserves_original_bounded_preparation_inputs(self):
        selection=dict(self.selection,angle_deg=30)
        with patch.object(S.C,'check',return_value={'route':'catalog'}) as reader:
            S.legacy_check(selection)
        actual=reader.call_args.args[0]
        self.assertNotIn('angle_deg',actual)
        self.assertEqual(actual['primary_count'],20)
        self.assertEqual(selection['angle_deg'],30)
        self.assertEqual(selection['primary_count'],25001)
    def test_angular_macros_only_add_precision_before_centre(self):
        import source_angle as A
        report={'volumes':[]}
        for angle in (-30,7.125,30):
            for source in (W.CS,'am241_point_decay_v1','ba133_point_decay_v1'):
                contract=S.C.source_preset(source)
                shared=dict(geometry_report_ref='unused',source_mode='cs137_legacy' if source==W.CS else 'registered_decay',
                    source_position_global_mm=A.Pose.resolve(angle)['position_global_mm'],source_contract=contract,
                    source_pose=A.Pose.resolve(angle),gps_precision_contract=A.GPS_PRECISION_CONTRACT)
                original=S.cs.macro_text(report,self.batch['primary_count'],shared['source_position_global_mm']) if source==W.CS else S.D.macro_text(report,self.batch['primary_count'],contract,shared['source_position_global_mm'])
                with patch.object(S.cs,'load',return_value=report),patch.object(S.P,'safe_path',return_value=Path('unused')):
                    actual=S.macro(shared,self.batch)
                self.assertEqual(actual.replace('/control/useDoublePrecision true\n',''),original)
                lines=actual.splitlines();index=next(i for i,line in enumerate(lines) if line.startswith('/gps/pos/centre '))
                self.assertEqual(lines[index-1],'/control/useDoublePrecision true')
                self.assertEqual(actual.count('/control/useDoublePrecision true'),1)
        with self.assertRaises(ValueError):A.precise_gps_macro('/run/beamOn 500\n')
        with self.assertRaises(ValueError):A.precise_gps_macro('/gps/pos/centre 1 2 3 mm\n/gps/pos/centre 1 2 3 mm\n')
    def test_angular_events_keep_raw_rows_and_global_identity(self):
        import source_angle as A
        event=dict(event_id=0,global_decay_id=0,steps=[dict(raw_row_index=8,time_ns=1200.25,energy_keV=0.01)])
        original=copy.deepcopy(event)
        shared=dict(model_id='SAP22',source_mode='cs137_legacy',source_pose={'angle_deg':30})
        with patch.object(A,'events',return_value=iter([event])) as reader:
            row=next(S.raw_events('unused',shared,self.batch))
        self.assertEqual(reader.call_args.args[1]['source_pose'],shared['source_pose'])
        self.assertEqual(row['global_initial_id'],20000)
        self.assertTrue(B.typed_equal({key:row[key] for key in original},original))
    def test_invalid_rehashed_ranges_bool_and_unsafe_global_offset_refused(self):
        for key,value in (('primary_count',True),('batch_index',1.),('global_initial_offset',B.MAX_SAFE_INTEGER),('local_initial_primary_id_range',[False,5000]),('global_initial_primary_id_range',[20000,25001])):
            batch=copy.deepcopy(self.batch);batch[key]=value
            with self.subTest(key=key),self.assertRaises((W.ControlError,ValueError)):S.validate_batch(batch)
        S.validate_batch(self.batch)

class SharedPreparation(unittest.TestCase):
    def prepared(self,angle=0):
        import source_angle as A
        import test_scenario_prepare as F
        folder=tempfile.TemporaryDirectory(prefix='batch-geometry-',dir=W.ROOT/'.local')
        self.addCleanup(folder.cleanup);out=Path(folder.name)/'shared'
        selection=dict(name='geometry-fixture',cryostat=W.CRYOSTAT,detector='SAP22',source=W.CS,
            pose='nominal',primary_count=100,seed=42,threads=1,electronics={})
        if angle:selection['angle_deg']=angle
        request=S.selection_request(selection)
        runtime={'kind':'synthetic-no-runtime'}
        original={'request':request,'execution_contract':{'kind':S.P.EXECUTION_KIND,'version':1,
            'source_mode':S.P.CS137,'exporter_sha256':'f'*64},'portable_source_sha256':{S.P.ADAPTER_REF:S.P.digest(S.P.adapter_path())},
            'runtime':runtime,'upstream_sha256':S.cs.upstream_hashes(),'gamma_plan':None}
        checked={'selection':selection,'legacy_geometry_plan':original}
        scenario=S.cs.load(W.ROOT/'transport/cryostat_nominal.json')
        source=scenario['source']['position_global_mm']
        if angle:
            pose=A.Pose.resolve(angle)
            angular={'source_pose':pose,'source_position_global_mm':pose['position_global_mm'],
                'source_contract':S.C.source_preset(W.CS),'source_mode':'cs137_legacy',
                'gps_precision_contract':A.GPS_PRECISION_CONTRACT,'runtime':runtime,'decay_data':None,'source_sha256':{}}
            checked['angle_geometry_plan']={**angular,'selection':dict(selection,primary_count=20)}
            checked['source_pose']=pose;source=pose['position_global_mm']
            mocked=patch.object(A,'check',return_value=checked['angle_geometry_plan']);mocked.start();self.addCleanup(mocked.stop)
        report=F.report_fixture({'assets':{'detector':{'id':'SAP22'}},'coordinate_transform':scenario['coordinate_transform'],
            'source_position_global_mm':source})
        if angle:
            for volume in report['volumes'][18:20]:volume['rotation_local_to_global']=pose['capsule_rotation_local_to_global']
            anchors=S.DW.anchors(W.ROOT)
            report['volumes'][17].update(translation_global_mm=[x+y for x,y in zip(anchors['expected_vacuum_global_translation_mm'],anchors['spacer']['vacuum_centre_mm'])],
                rotation_local_to_global=A.assembly.ROTATION)
        def runtime_data(output,identity,mode):
            (output/'runtime').mkdir()
            S.h.publish_json(output/'runtime/emlow-data.json',{'kind':'synthetic-fixture'})
            S.h.publish_json(output/'runtime/runtime.json',{'identity':identity})
        def exporter(command,**kwargs):
            Path(command[-2]).write_text('<gdml><!-- SYNTHETIC UNIT FIXTURE --></gdml>\n',encoding='utf-8')
            Path(command[-1]).write_text(S.P.text(report),encoding='utf-8')
            kwargs['stdout'].write('Synthetic geometry fixture; no exporter or simulation ran.\n')
            return types.SimpleNamespace(returncode=0)
        for obj,name,kwargs in ((S,'check',{'return_value':checked}),(S.P,'validate_checked_plan',{'return_value':original}),
                (S.P,'recheck_runtime_data',{'return_value':0}),(S.P,'runtime_data',{'side_effect':runtime_data}),
                (S.P.subprocess,'run',{'side_effect':exporter})):
            mocked=patch.object(obj,name,**kwargs);mocked.start();self.addCleanup(mocked.stop)
        shared=S.prepare(selection,out,checked)
        return out,shared,report

    def test_nominal_sap22_shared_report_reaches_native_contract(self):
        out,shared,report=self.prepared()
        self.assertNotIn('geometry_checks',S.cs.load(out/'legacy/prepared.json'))
        self.assertEqual(shared['geometry_checks'],report)
        self.assertIs(shared['geometry_checks']['overlaps_passed'],True)
        self.assertIs(shared['geometry_checks']['source_inside_fill'],True)
        self.assertEqual(W.encoded(S.read_shared(out/'prepared.json')),W.encoded(shared))
        batch=E.batch_at(E.partition(100,42),0)
        self.assertIn('/run/beamOn 100\n',S.macro(shared,batch))
        # Rehashing the inline copy must not override its checked report file.
        altered=copy.deepcopy(shared);altered['geometry_checks']['overlaps_passed']=False
        (out/'prepared.json').write_text(S.P.text(altered),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'source/geometry/model/unit/clock'):
            S.read_shared(out/'prepared.json')

    def test_angular_sap22_preparation_preserves_report_and_pose(self):
        out,shared,report=self.prepared(30)
        self.assertEqual(shared['geometry_checks'],report)
        self.assertEqual(shared['source_pose']['angle_deg'],30)
        self.assertEqual(W.encoded(S.read_shared(out/'prepared.json')),W.encoded(shared))
        self.assertIn('/control/useDoublePrecision true\n/gps/pos/centre ',
            S.macro(shared,E.batch_at(E.partition(100,42),0)))

    def test_legacy_shared_report_ref_stays_readable_without_rewriting(self):
        out,shared,_=self.prepared();shared.pop('geometry_checks')
        path=out/'prepared.json';path.write_text(S.P.text(shared),encoding='utf-8')
        before=S.h.sha256(path)
        self.assertEqual(W.encoded(S.read_shared(path)),W.encoded(shared))
        self.assertEqual(S.h.sha256(path),before)


if __name__=='__main__':unittest.main()
