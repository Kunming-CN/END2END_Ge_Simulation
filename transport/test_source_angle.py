"""Focused source pose, actual-solid screen and independent native-report checks."""
import copy, math, unittest
from unittest.mock import patch
import source_pose as P
import source_angle as A
import handoff as h
import scenario_prepare as assembly
import test_scenario_prepare as F


class SourceAngleTests(unittest.TestCase):
    def fixture(self, theta=30):
        geometry = A.model_geometry('SAP22')
        pose = P.resolve(theta)
        plan = {'assets':{'detector':{'id':'SAP22'}},'coordinate_transform':A.DW.anchors(h.ROOT)['coordinate_transform'],
                'source_position_global_mm':pose['position_global_mm']}
        report = F.report_fixture(plan)
        a = A.DW.anchors(h.ROOT)
        report['volumes'][17].update(translation_global_mm=[x+y for x,y in zip(a['expected_vacuum_global_translation_mm'],a['spacer']['vacuum_centre_mm'])],
                                     rotation_local_to_global=assembly.ROTATION)
        for v in report['volumes'][18:20]: v['rotation_local_to_global'] = pose['capsule_rotation_local_to_global']
        return copy.deepcopy(report), {'source_pose':pose}, geometry

    def test_zero_is_exact_frozen_anchor_and_rotation(self):
        for value in (0,0.0,-0.0):
            pose = P.resolve(value)
            self.assertEqual(pose['position_global_mm'],[0,37.073,.290])
            self.assertEqual(pose['capsule_rotation_local_to_global'],assembly.ROTATION)
        self.assertEqual(P.angle({}),0)
        self.assertEqual(P.angle({'source':A.W.GAMMA,'angle_deg':0}),0)

    def test_signed_pose_radius_axis_rotation_and_native_checks(self):
        for theta in (-30,-12.5,12.5,30):
            p = P.resolve(theta); x,y,z = p['position_global_mm']
            self.assertAlmostEqual(math.hypot(x,y-1.473),35.6,places=12)
            self.assertEqual(z,.290)
            rotation = p['capsule_rotation_local_to_global']
            self.assertEqual([row[2] for row in rotation],p['capsule_axis_global'])
            h.validate_transform({'definition':h.TRANSFORM['definition'],'rotation_local_to_global':rotation,
                                  'translation_global_mm':p['position_global_mm']})
            report,checked,geometry = self.fixture(theta)
            A.validate_report(report,checked,geometry)

    def test_invalid_angle_and_gamma_are_refused(self):
        for value in (True,False,'30',None,math.nan,math.inf,-math.inf,30.001,-30.001,10**400):
            with self.subTest(value=repr(value)), self.assertRaises(A.W.ControlError): P.degrees(value)
        with self.assertRaises(A.W.ControlError): P.angle({'source':A.W.GAMMA,'angle_deg':30})

    def test_conservative_actual_solid_screen_for_both_signs(self):
        for theta in (-30,0,30):
            screen = P.geometry_screen(P.resolve(theta))
            self.assertTrue(screen['passed'])
            self.assertEqual(screen['capsule_inward_radial_plane_mm'],screen['shell_outer_radius_mm'])
            self.assertLess(screen['world_radial_upper_bound_mm'],screen['world_radius_mm'])

    def test_independent_report_refuses_source_and_unchanged_parts(self):
        edits = [lambda r:r['volumes'][18]['translation_global_mm'].__setitem__(0,0),
                 lambda r:r['volumes'][19].update(rotation_local_to_global=assembly.ROTATION),
                 lambda r:r['volumes'][17].update(rotation_local_to_global=P.resolve(30)['capsule_rotation_local_to_global']),
                 lambda r:r['volumes'][16]['translation_global_mm'].__setitem__(2,1),
                 lambda r:r['volumes'][18].update(material='G4_Cu'),
                 lambda r:r['volumes'][18].update(overlap=True),
                 lambda r:r.update(overlaps_passed=False),lambda r:r.update(source_inside_fill=1),
                 lambda r:r['probes'][0].update(classification='inside' if r['probes'][0]['classification'] != 'inside' else 'outside')]
        for index,edit in enumerate(edits):
            report,checked,geometry = self.fixture(); edit(report)
            with self.subTest(index=index), self.assertRaises((ValueError,KeyError)): A.validate_report(report,checked,geometry)

    def test_old_geometry_helpers_and_model_contracts_are_reused(self):
        for model in (*A.W.MODELS,'AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'):
            with self.subTest(model=model):
                geometry = A.model_geometry(model)
                self.assertTrue(geometry['probes'])
                self.assertIn('<gdml',geometry['canonical_gdml'])
                if model in A.W.MODELS: self.assertEqual(A.DW.operating(model)['runtime_temperature_K'] if 'runtime_temperature_K' in A.DW.operating(model) else A.DW.numerics(model)['runtime_temperature_K'],77)

    def test_new_native_parameter_and_source_macro_are_literal(self):
        source = A.C.source_preset(A.W.CS)
        checked = {'source_pose':P.resolve(30),'source_contract':source}
        mount = A.scenario(checked)
        self.assertEqual(len(A.parameter_text(mount).split()),19)
        self.assertTrue(A.parameter_text(mount).endswith(' 30\n'))
        report,_,_ = self.fixture()
        meta = {'geometry_checks':report,'source_mode':'cs137_legacy','primary_count':500,
                'source_position_global_mm':checked['source_pose']['position_global_mm']}
        macro = A.macro(meta)
        self.assertIn('/run/beamOn 500',macro)
        self.assertIn('/gps/ion 55 137',macro)
        self.assertNotIn('/gps/ang/direction',macro)
        self.assertIn(' '.join(format(v,'.17g') for v in meta['source_position_global_mm']),macro)
        original=A.cs.macro_text(report,500,meta['source_position_global_mm'])
        self.assertEqual(macro.replace('/control/useDoublePrecision true\n',''),original)
        self.assertIn('/control/useDoublePrecision true\n/gps/pos/centre ',macro)

    def test_event_reader_delegates_without_changing_raw_ledger(self):
        event = {'event_id':0,'global_decay_id':0,'steps':[], 'vtx':[{'time':0}], 'tracks':[{'time':900001.25}]}
        before = copy.deepcopy(event)
        with patch.object(A.C,'events',return_value=iter([event])) as reader:
            self.assertEqual(list(A.events('truth',{'source_mode':'cs137_legacy'})),[before])
            self.assertEqual(reader.call_count,1)


if __name__ == '__main__': unittest.main()
