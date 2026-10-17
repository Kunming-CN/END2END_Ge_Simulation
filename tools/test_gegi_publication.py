"""Saved GeGI publication rendering and snapshot-only dispatch; no science."""
from pathlib import Path
import copy
import math
import tempfile
import unittest
from unittest.mock import patch

import gegi_publication as P
import scenario_workflow as W


class GeGIPublication(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-publication-',dir=W.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)
        asset=self.root/P.ASSET;asset.parent.mkdir(parents=True);asset.write_bytes((W.ROOT/P.ASSET).read_bytes())
        self.source=W.run_path('gegi-owned',self.root);self.site=self.root/'site'
        detector=self.site/'detectors/GeGI_3D/index.html';detector.parent.mkdir(parents=True)
        detector.write_text('<html><body><main><p>Earlier saved study.</p></main></body></html>')
        self.resolved={'selection':{'name':'gegi-owned','cryostat':P.G.CRYOSTAT,'detector':'GeGI_3D',
            'source':P.G.SOURCE,'pose':'custom','primary_count':100,'seed':26101701,'threads':1,
            'gamma_energy_keV':662.,'source_position_mm':[0.,0.,100.],'electronics':{}},
            'model_sha256':P.G.MODEL_SHA,'numerics':{'drift_dt_ns':1.},
            'source_sha256':{P.ASSET:P.sha(asset),'tools/gegi_response.py':'b'*64,'.local/private-cache':'c'*64}}
        self.config=W.digest(self.resolved)
        trace={'time_ns':[0.,1.,2.],'charge_fC':[0.,-.1234567890123456,-.2],
               'current_nA':[0.,-1.,-2.],'preamp_V':[0.,-.01,-.02],'shaped_V':[0.,.01,.02]}
        self.payload={'kind':'gegi_multichannel_results_v1','configuration_sha256':self.config,
            'counts':{'initial_primaries':100,'zero_deposit_primaries':99,'nonzero_primaries':1,'native_failed_groups':0},
            'channels':[{'id':i,'name':('X' if i<=17 else 'Y')+str(i),'family':'X' if i<=17 else 'Y',
                         'potential_V':-879 if i<=17 else 0,'wiring_factor':1 if i<=17 else -1} for i in range(1,35)],
            'events':[{'event_id':37,'truth_edep_keV':20.,'status':'native_completed','channels':[
                {'contact_id':1,'final_induced_keV':19.8,'reconstructed_energy_keV':19.5,'trace':trace}]}],
            'imaging':{'method':'Signal-derived Compton backprojection','accepted_events':0,'rejected_events':1,
                'ambiguous_events':0,'azimuth_deg':[-180.,0.],'elevation_deg':[-45.,45.],
                'values':[[0.,0.],[0.,0.]],'selection':{'minimum_collected_energy_keV':5.},
                'cones':[],'limitations':['No selected two-site event.']},'limitations':['Engineering geometry.']}
        self.save()

    def save(self):
        W.write(self.source/'resolved-config.json',{'kind':P.G.KIND,'resolved':self.resolved,'configuration_sha256':self.config})
        W.write(self.source/'response/results.json',self.payload)
        W.write(self.source/'response/run.json',{'configuration_sha256':self.config,'counts':self.payload['counts']})
        W.write(self.source/'COMPLETE.json',{'kind':P.G.KIND,'configuration_sha256':self.config,
            'artifacts':W.inventory(self.source,exclude=('COMPLETE.json',))})
        self.receipt={'status':'completed','verification':'terminal_artifacts_verified','configuration_sha256':self.config}

    def assemble(self):
        with patch.object(P.G,'inspect',return_value=self.receipt),patch.object(P.G,'query',side_effect=AssertionError('No transport query')):
            return P.assemble(self.source,self.site,root=self.root)

    def test_renders_real_selected_values_sparse_census_geometry_and_blank_image(self):
        target=self.assemble();summary=W.read(target/'summary.json');selected=W.read(target/'selected-channel.json')
        self.assertEqual(summary['stored_nonzero_ids'],[37]);self.assertEqual(summary['counts']['initial_primaries'],100)
        self.assertEqual(selected['channel']['trace']['charge_fC'][1],-.1234567890123456)
        self.assertEqual(summary['cryostat']['measured_front']['crystal_to_outer_front_mm'],8.1)
        self.assertNotIn('source',summary['cryostat']['measured_front'])
        self.assertNotIn('.local/private-cache',summary['public_source_sha256'])
        page=(target/'index.html').read_text()
        for text in ('99','original signed analog samples','blank image','nominal side/rear','−879 V','signal','8.1 mm'):
            self.assertIn(text,page)
        self.assertNotIn('C:\\Users',page);self.assertNotIn('baseline_simulation',page)
        first=(self.site/'detectors/GeGI_3D/index.html').read_bytes();P.link_current(self.site)
        self.assertEqual(first,(self.site/'detectors/GeGI_3D/index.html').read_bytes())
        self.assertEqual(first.count(b'id="gegi-control-results"'),1)
        self.assertIn(b'Earlier saved study.',first)
        P.validate_bundle(target)

    def test_all_zero_run_has_no_fabricated_channel(self):
        self.payload['events']=[];self.payload['counts'].update(zero_deposit_primaries=100,nonzero_primaries=0);self.save()
        target=self.assemble();self.assertIsNone(W.read(target/'selected-channel.json')['channel'])
        self.assertIn('No zero waveform is fabricated',(target/'index.html').read_text())
        self.assertNotIn('<polyline',(target/'index.html').read_text())

    def test_native_failure_has_unknown_channels_and_is_skipped_for_plot_selection(self):
        self.payload['events'].insert(0,{'event_id':2,'truth_edep_keV':4.,'status':'native_failed','channels':None})
        self.payload['counts'].update(zero_deposit_primaries=98,nonzero_primaries=2,native_failed_groups=1)
        self.save();target=self.assemble()
        self.assertEqual(W.read(target/'summary.json')['stored_nonzero_ids'],[2,37])
        self.assertEqual(W.read(target/'selected-channel.json')['event_id'],37)
        self.payload['events']=self.payload['events'][:1]
        selected=P.selected_channel(self.payload)
        self.assertIsNone(selected['event_id']);self.assertIsNone(selected['channel'])

    def test_changed_science_input_is_refused_before_publication(self):
        (self.source/'response/results.json').write_bytes(b'{}')
        with self.assertRaisesRegex(ValueError,'input changed'):self.assemble()
        self.assertFalse((self.site/'examples/gegi').exists())

    def test_private_path_or_changed_public_artifact_is_refused(self):
        self.payload['limitations']=['Private C:\\Users\\owner\\data'];self.save()
        with self.assertRaisesRegex(ValueError,'Private paths'):self.assemble()
        self.payload['limitations']=[];self.save();target=self.assemble()
        (target/'summary.json').write_text('{}')
        with self.assertRaisesRegex(ValueError,'publication changed'):P.link_current(self.site)

    def test_build_mode_copies_snapshot_and_never_rebuilds_gallery(self):
        import build_site as B
        import viewer_navigation as V
        (self.site/'index.html').write_text('<html><title>Saved site</title><main>Original snapshot</main></html>')
        (self.site/B.MANIFEST).write_text('{}')
        out=self.root/'.local/site-build'
        with (patch.object(P.G,'inspect',return_value=self.receipt),patch.object(P.G,'query',side_effect=AssertionError('No transport')),
              patch.object(B,'ROOT',self.root),patch.object(B,'DESTINATION',self.site),patch.object(B,'OUT',out),
              patch.object(B,'validate',return_value={'build_id':'saved'}),
              patch.object(B,'build_export',side_effect=AssertionError('No gallery regeneration')),
              patch.object(B,'install_snapshot',side_effect=lambda old:{'copied':(out/'index.html').read_text(),'gegi':(out/'examples/gegi/index.html').exists()}),
              patch.object(V,'assemble')):
            result=B.build(gegi_results=self.source)
        self.assertTrue(result['gegi']);self.assertIn('Original snapshot',result['copied'])
        self.assertFalse((self.site/'examples/gegi').exists())

    def test_plane_uses_vertex_preserves_weight_and_has_no_truth_input(self):
        cone={'event_id':37,'vertex_mm':[10.,0.,0.],'axis':[0.,0.,1.],
              'half_angle_deg':45.,'weight':1.}
        plane=P.planar_backproject([cone],40.)
        self.assertAlmostEqual(math.fsum(v for row in plane['values'] for v in row)*6.25,1.,places=12)
        row=plane['values'][40]
        self.assertGreater(row[60],row[44]*1e12)  # x=50 lies on the cone; x=10 is its axis.
        changed=dict(cone,source_truth_mm=[-300,90,-200],source_run_key='other')
        self.assertEqual(P.planar_backproject([changed],40.)['values'],plane['values'])
        self.assertFalse(plane['unmapped_cones'])

    def test_two_runs_keep_qualified_ids_denominators_and_sum_maps(self):
        with patch.object(P.G,'inspect',return_value=self.receipt):
            first,choice,asset=P.compact_source(self.source,self.root)
        first['source_run_key']='source_1'
        first['imaging'].update(accepted_events=1,rejected_events=0,ambiguous_events=0,
            cones=[{'event_id':37,'vertex_mm':[0.,0.,0.],'axis':[0.,0.,1.],
                    'half_angle_deg':45.,'weight':1.}],values=[[.1,.2],[.3,.4]])
        second=copy.deepcopy(first);second['source_run_key']='source_2'
        second['configuration_sha256']='d'*64;second['selection']['source_position_mm']=[40.,0.,40.]
        result=P.combine_sources([first,second],40.)
        self.assertEqual(result['counts']['initial_primaries'],200)
        self.assertEqual(result['counts']['zero_deposit_primaries'],198)
        self.assertEqual(result['stored_event_keys'],[
            {'source_run_key':'source_1','event_id':37},{'source_run_key':'source_2','event_id':37}])
        self.assertEqual(result['imaging']['values'],[[.2,.4],[.6,.8]])
        self.assertAlmostEqual(math.fsum(v for row in result['planar_imaging']['values'] for v in row)*6.25,2.,places=12)
        page=P.render_comparison(result,[dict(choice,source_run_key='source_1'),dict(choice,source_run_key='source_2')],[asset,asset])
        self.assertTrue(b'inconclusive' in page.lower(),'The comparison must state its inconclusive separation result.')
        second['selection']['gamma_energy_keV']=1000.
        with self.assertRaisesRegex(ValueError,'gamma_energy'):P.combine_sources([first,second],40.)


if __name__=='__main__':unittest.main()
