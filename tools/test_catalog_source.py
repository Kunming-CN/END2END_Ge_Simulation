"""Injected source reader identity and rehashed metadata guards; no science."""
import copy,json,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'transport'))
import catalog_source as S

class CatalogSourceTests(unittest.TestCase):
    def test_original_reader_rows_and_ids_are_retained(self):
        original=S.h.membership;raw={'event_id':0,'global_decay_id':0,'steps':[{'raw_row_index':7,'energy_keV':1.2,'time_ns':0.}]}
        geometry={'box':{'widths':[2.,2.,2.],'origin':{'x':0.,'y':0.,'z':1.}}}
        def reader(path,meta):
            self.assertEqual(S.h.membership({'catalog_geometry':geometry},[0.,0.,1.]),'inside')
            yield raw
        for mode,module in (('cs137_legacy',S.cs),('registered_decay',S.D)):
            with patch.object(module,'iter_decays',side_effect=reader):
                result=list(S.events('unused',{'source_mode':mode}));self.assertIs(result[0],raw)
            self.assertIs(S.h.membership,original)
    def test_membership_hook_restores_after_raw_reader_failure(self):
        original=S.h.membership
        def broken(path,meta):
            raise RuntimeError('injected raw table failure')
            yield None
        with patch.object(S.cs,'iter_decays',side_effect=broken),self.assertRaises(RuntimeError):
            list(S.events('unused',{'source_mode':'cs137_legacy'}))
        self.assertIs(S.h.membership,original)
    def test_rehashed_prepared_coordinates_policies_and_native_parameters_refused(self):
        with tempfile.TemporaryDirectory(prefix='catalog-injected-',dir=S.h.ROOT/'.local') as tmp:
            d=Path(tmp);model=S.G.load_model('Bipolar_reference_3D');selection={'name':'injected','cryostat':S.W.CRYOSTAT,'detector':model['model_id'],
                'source':S.W.CS,'pose':'nominal','primary_count':20,'seed':26092631,'threads':1,'electronics':{}}
            source=S.source_preset(selection['source']);position=S.DW.anchors(S.h.ROOT)['source_pose']['position_global_mm']
            checked={'selection':selection,'model_contract':model,'source_contract':source,'source_mode':'cs137_legacy','source_position_global_mm':position,
                'source_sha256':{},'runtime':{'fixture':True},'decay_data':None}
            probes=S.G.probes(model['geometry']);tr=model['cavity']['coordinate_transform']
            report={'overlaps_passed':True,'source_inside_fill':True,'volumes':[{'name':'germanium','material':'G4_Ge',
                'translation_global_mm':tr['translation_global_mm'],'rotation_local_to_global':tr['rotation_local_to_global']}],
                'probes':[{'index':i,'classification':p['expected']} for i,p in enumerate(probes)]}
            mount=S.cs.load(S.h.ROOT/'transport/cryostat_nominal.json');(d/'runtime').mkdir()
            for name,value in (('checked-plan.json',checked),('geometry-report.json',report),('scenario.json',mount),('runtime/runtime.json',{'identity':checked['runtime']})):
                S.h.publish_json(d/name,value)
            for name,text in (('canonical.gdml',S.G.gdml_text(model['geometry'])),('probe-points.txt',S.P.probe_text(probes)),('parameters.txt',S.P.parameter_text(mount,position,False))):
                S.h.write_new(d/name,text)
            meta={'kind':S.PREPARED_KIND,'status':'complete','schema_version':1,'producer_adapter':S.ADAPTER,'selection':selection,'model_contract':model,
                'source_contract':source,'model_id':model['model_id'],'model_sha256':model['model_sha256'],'source_id':source['id'],'source_mode':'cs137_legacy','source_pdg':S.source_pdg(source,'cs137_legacy'),
                'primary_count':20,'seed':selection['seed'],'source_position_global_mm':position,'clock_policy':'remage_initial_decay_secondaries_zero','daughter_lifetime_limit_ns':-1,
                'coordinate_transform':S.DW.anchors(S.h.ROOT)['coordinate_transform'],'grouping_policy':dict(S.cs.POLICY),'geometry_checks':report,'probes':probes,
                'mass_geometry':model['geometry'],'contour_rz_mm':{'catalog_geometry':model['geometry']},'source_sha256':{},'upstream_sha256':S.cs.upstream_hashes(),
                'decay_photon_line_window_keV':S.cs.LINE,'material_tables':{'stp/germanium':'G4_Ge'},
                'unscored_volumes':[{'name':'ledger_0_PV','material':'G4_AIR','reason':'unscored world; no full energy closure claim'}]}
            # Macro construction requires the native source-fill volume geometry.
            with patch.object(S,'macro',return_value='fixed macro\n'),patch.object(S,'check',return_value=checked),patch.object(S.P,'recheck_runtime_data'):
                S.h.write_new(d/'run.mac',S.macro(meta));meta['files_sha256']={f.relative_to(d).as_posix():S.h.sha256(f) for f in d.rglob('*') if f.is_file()}
                S.h.publish_json(d/'prepared.json',meta);S.read_prepared(d)
                for mutate in (lambda m:m['coordinate_transform'].update(translation_global_mm=[0,0,0]),
                    lambda m:m.update(clock_policy='raw_clock'),lambda m:m.update(material_tables={'stp/germanium':'G4_AIR'})):
                    edited=copy.deepcopy(meta);mutate(edited);(d/'prepared.json').write_bytes(S.W.encoded(edited))
                    with self.assertRaises((ValueError,RuntimeError)):S.read_prepared(d)
                (d/'parameters.txt').write_text('0 '*18+'\n',encoding='utf-8');meta['files_sha256']['parameters.txt']=S.h.sha256(d/'parameters.txt')
                (d/'prepared.json').write_bytes(S.W.encoded(meta))
                with self.assertRaises((ValueError,RuntimeError)):S.read_prepared(d)

if __name__=='__main__':unittest.main()
