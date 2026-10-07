"""Pure catalog/CSG checks in the installed transport Python; no workers."""
import copy,json,math,unittest
import xml.etree.ElementTree as ET
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'transport'))
import catalog_geometry as G

class CatalogGeometryTests(unittest.TestCase):
    def test_all_seventeen_input_contracts_and_five_new_envelopes(self):
        catalog=json.loads((G.h.ROOT/'models/catalog.json').read_text());items={d['id']:G.load_model(d['id']) for d in catalog['detectors']}
        self.assertEqual(len(items),17)
        added={id for id,c in items.items() if id not in G.OLD_MODELS and not c['placement']['blocking_reasons']}
        self.assertEqual(added,{'AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'})
        self.assertEqual(sum(bool(c['placement']['blocking_reasons']) for c in items.values()),7)
        self.assertEqual(items['GeGI_3D']['stored_temperature_K'],92.3);self.assertEqual(items['GeGI_3D']['readout_contact_id'],9)
        self.assertEqual(len(items['GeGI_3D']['contact_potentials_V']),34)
        for id,c in items.items():self.assertEqual(c['stored_temperature_K'],c['runtime_temperature_K'])
    def test_fixed_cavity_dimensions_are_derived_from_original_inputs(self):
        c=G.cavity_contract();b=c['large_box_bounds_vacuum_mm']
        for actual,expected in zip(b,[-20.574,20.574,-21.463,21.463,-29.21,29.21]):self.assertAlmostEqual(actual,expected,places=10)
        self.assertEqual(c['crystal_in_vacuum_translation_mm'],[0,-.023,4]);self.assertAlmostEqual(c['maximum_front_z_mm'],35.56)
    def test_new_model_gdml_keeps_original_box_origins(self):
        for id in ('Bipolar_reference_3D','KL01_3D'):
            c=G.load_model(id);xml=ET.fromstring(G.gdml_text(c['geometry']))
            boxes=xml.findall('./solids/box');self.assertGreater(len(boxes),1)
            placed=xml.findall('./solids/multiUnion/multiUnionNode');self.assertEqual(len(placed),1 if id=='Bipolar_reference_3D' else 6)
            if id=='Bipolar_reference_3D':self.assertEqual(float(placed[0].find('position').get('z')),4.75)
            self.assertEqual(xml.find('./structure/volume[@name="world"]/physvol/position').get('z'),'0')
    def test_union_tubes_and_nonorthogonal_polycone_are_exact_primitives(self):
        for id in ('SAP16','SAP17','PPC_PONaMa1_reference'):
            c=G.load_model(id);xml=ET.fromstring(G.gdml_text(c['geometry']))
            if id.startswith('SAP'):self.assertEqual(len(xml.findall('./solids/tube')),5)
            else:
                actual=xml.findall('./solids/genericPolycone/rzpoint');expected=c['geometry']['polycone']
                self.assertEqual([(float(p.get('r')),float(p.get('z'))) for p in actual],list(zip(expected['r'][:-1],expected['z'][:-1])))
    def test_box_membership_uses_model_origin_without_retiming_or_shifting_rows(self):
        c=G.load_model('Bipolar_reference_3D');g=c['geometry']
        self.assertEqual(G.membership(g,[0,0,4.75]),'inside');self.assertEqual(G.membership(g,[0,0,0]),'surface')
        self.assertEqual(G.membership(g,[0,0,-.01]),'outside');self.assertEqual(G.membership(g,[5,0,4.75]),'outside')
    def test_union_internal_touching_face_is_not_a_physical_surface(self):
        g={'union':[{'tube':{'r':{'from':0,'to':1},'h':2,'origin':{'z':1}}},{'tube':{'r':{'from':1,'to':2},'h':2,'origin':{'z':1}}}]}
        self.assertEqual(G.membership(g,[1,0,1]),'inside');self.assertEqual(G.membership(g,[2,0,1]),'surface')
    def test_bad_geometry_parameters_fail_without_native_dispatch(self):
        for g in ({'sphere':{'r':1}},{'box':{'widths':[1,1,0]}},{'tube':{'r':1,'h':0}},
                  {'box':{'widths':[1,1,1],'rotate':{'X':90}}},{'union':[]}):
            with self.subTest(shape=g),self.assertRaises(ValueError):G.validate_geometry(g)
    def test_probe_records_preserve_original_coordinates_and_labels(self):
        for id in ('AK01','SAP16','SAP17','Bipolar_reference_3D','KL01_3D'):
            g=G.load_model(id)['geometry'];before=copy.deepcopy(g);probes=G.probes(g)
            self.assertEqual(g,before);self.assertTrue({'inside','outside','surface'}<={p['expected'] for p in probes})
            self.assertTrue(all(p['expected']==G.membership(g,p['position_mm']) for p in probes))

if __name__=='__main__':unittest.main()
