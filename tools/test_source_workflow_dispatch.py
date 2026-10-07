"""Shared-source dispatch contracts. No radiation, fields or drift are launched."""
import copy
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import scenario_workflow as W
import decay_workflow as D


class SourceDispatch(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.default=W.read(W.ROOT/'simulation/native_readout_profile.json')['settings']
        self.config=dict(name='shared-source-fixture',cryostat=W.CRYOSTAT,detector='SAP22',
            source='am241_point_decay_v1',pose='nominal',primary_count=500,seed=26092631,
            threads=1,electronics=copy.deepcopy(self.default))

    def test_all_five_detectors_use_one_generic_boundary(self):
        for model in W.MODELS:
            c=dict(self.config,detector=model)
            with self.subTest(model=model),patch.object(D,'check',return_value={'sentinel':model}) as shared,patch.object(W,'_resolve',side_effect=AssertionError('legacy dispatch called')):
                result=W.check(c,root=self.root,bootstrap_source=True)
            self.assertEqual(result,{'sentinel':model})
            args=shared.call_args
            self.assertEqual(args.args,(c,))
            self.assertEqual(args.kwargs['root'],self.root)
            self.assertIs(args.kwargs['bootstrap_source'],True)

    def test_bootstrap_is_explicit_and_never_a_gui_default(self):
        with patch.object(D,'check',return_value={}) as shared:
            W.check(self.config,root=self.root)
        self.assertIs(shared.call_args.kwargs['bootstrap_source'],False)
        for source in (W.CS,W.GAMMA):
            with self.subTest(source=source),self.assertRaises(W.ControlError):
                W.check(dict(self.config,source=source),root=self.root,bootstrap_source=True)

    def test_generic_plan_admission_and_saved_validation_use_marker(self):
        plan={'resolved':{'decay_source_contract':{'id':self.config['source']}}}
        with patch.object(D,'admit',return_value=plan) as live:
            self.assertIs(W.admit(plan,self.root,resume=True,bootstrap_source=True),plan)
        live.assert_called_once_with(plan,self.root,resume=True,bootstrap_source=True)
        with patch.object(D,'saved_plan',return_value='historical') as saved:
            self.assertEqual(W.saved_plan(plan,self.root),'historical')
        saved.assert_called_once_with(plan,self.root)

    def test_command_and_portable_stage_dispatch_do_not_choose_detector_aliases(self):
        for model in W.MODELS:
            resolved={'selection':dict(self.config,detector=model),'decay_source_contract':{'id':self.config['source']}}
            directory=W.run_path(self.config['name'],self.root)
            env={'JULIA_EXE':'existing-julia.exe'}
            with self.subTest(model=model),patch.object(D,'stage_commands',return_value={'response':['generic']}) as command:
                self.assertEqual(W.stage_commands(directory,resolved,self.root,env),{'response':['generic']})
            command.assert_called_once_with(directory,resolved,self.root,env)
            with patch.object(D,'portable_stage',return_value={'verified':True}) as stage:
                self.assertEqual(W.portable_stage(directory,resolved,'event_ledger',self.root),{'verified':True})
            stage.assert_called_once_with(directory,resolved,'event_ledger',self.root)

    def test_catalog_preserves_seventeen_views_five_connectors_and_shared_sources(self):
        catalog=W.catalog()
        self.assertEqual(len(catalog['detectors']),17)
        available=[d for d in catalog['detectors'] if d['available']]
        self.assertEqual({d['id'] for d in available},set(W.MODELS))
        sources={s['id']:s for s in catalog['sources']}
        generic={id for id,s in sources.items() if s['source_contract']['adapter']=='shared_decay_source_v1'}
        self.assertEqual(generic,{'am241_point_decay_v1','co60_point_decay_v1','ba133_point_decay_v1'})
        for detector in available:
            self.assertTrue(generic.issubset(detector['sources']))
        for source in sources.values():
            self.assertTrue(source['label'])
            self.assertTrue(source['details'])
            self.assertTrue(source['count_unit'])
            self.assertEqual(source['counts'],source['source_contract']['counts'])
        self.assertEqual(sources[W.GAMMA]['fixed_seed'],26092631)
        self.assertEqual(sources['am241_point_decay_v1']['position_global_mm'],[0,37.073,.290])

    def test_real_resolver_composes_three_sources_with_all_five_models(self):
        validated=W.settings_check(self.default)
        anchors=D.anchors()
        sources=[p for p in D.presets() if p['adapter']==D.ADAPTER]
        configs=set()
        def portable(c,root):
            return {'kind':'decay_source_checked_plan_v1','schema_version':1,
                'request':W.portable_request(c),'source_contract':D.preset(c['source']),
                'placement_contract':anchors,'portable_source_sha256':{'public-producer.py':'d'*64}}
        for source in sources:
            for model in W.MODELS:
                c=dict(self.config,source=source['id'],detector=model)
                with self.subTest(source=source['id'],model=model):
                    plan=W.check(c,root=W.ROOT,bootstrap_source=True,
                        validate_settings=lambda *_:copy.deepcopy(validated),
                        pin_reader=lambda *_:{'public-source.py':'a'*64},
                        runtime_reader=lambda *_:{'python_sha256':'b'*64,'julia_sha256':'c'*64},
                        portable_reader=portable)
                    r=plan['resolved'];W.saved_plan(plan)
                    self.assertEqual(r['selection'],c)
                    self.assertEqual(r['source_count_unit'],source['count_unit'])
                    self.assertEqual(r['decay_source_contract'],source)
                    self.assertEqual(r['placement_contract'],anchors)
                    self.assertEqual(r['source_position_global_mm'],[0,37.073,.290])
                    self.assertEqual(r['operating_model'],D.operating(model))
                    self.assertEqual(r['numerics'],D.numerics(model))
                    commands=W.stage_commands(W.run_path(c['name']),r,W.ROOT,{'JULIA_EXE':'installed-julia.exe'})
                    self.assertIn('./decay_source.py',commands['radiation'])
                    self.assertIn(str(W.ROOT/'simulation/workflow_decay_response.jl'),commands['response'])
                    configs.add(plan['configuration_sha256'])
        self.assertEqual(len(configs),15)

    def test_pending_and_malformed_capabilities_fail_before_preflight(self):
        source=D.preset(self.config['source'])
        original=W.read(W.ROOT/'scenarios/detector-capabilities.json')
        pending=copy.deepcopy(original);pending.get('source_adapters',{}).pop(source['id'],None)
        acceptance={'status':'accepted','detector':'SAP22','primary_count':500,'seed':26092631,
            'accepted_groups':1,'native_failed_groups':0,'readout_rejected':0,'saturated_groups':0,
            'configuration_sha256':'a'*64,'complete_sha256':'b'*64,'source_contract_sha256':W.digest(source),
            'run_ref':W.BASE+'/source-am241-500-v1'}
        valid={'adapter':D.ADAPTER,'detectors':list(W.MODELS),'counts':[20,500],'pose':'nominal','acceptance':acceptance}
        reader=W.read
        mutations=(lambda v:v['acceptance'].update(accepted_groups=0),
            lambda v:v['acceptance'].update(accepted_groups=True),
            lambda v:v['acceptance'].update(native_failed_groups=1),
            lambda v:v['acceptance'].update(detector='AK02'),
            lambda v:v['acceptance'].update(source_contract_sha256='0'*64),
            lambda v:v['acceptance'].pop('complete_sha256'),
            lambda v:v.update(detectors=['SAP22']),lambda v:v.update(counts=[20,500,10000]))
        for mutation in (None,*mutations):
            changed=copy.deepcopy(pending)
            if mutation is not None:
                record=copy.deepcopy(valid);mutation(record)
                changed.setdefault('source_adapters',{})[source['id']]=record
            with self.subTest(mutation=mutation),patch.object(W,'read',side_effect=lambda path:changed if str(path).endswith('detector-capabilities.json') else reader(path)),patch.object(D,'portable_check',side_effect=AssertionError('preflight must not run')):
                with self.assertRaises(W.ControlError):W.check(self.config,root=W.ROOT)
                if mutation is not None:
                    with self.assertRaises(W.ControlError):W.check(self.config,root=W.ROOT,bootstrap_source=True)

    def test_historical_legacy_plans_keep_original_source_hashes(self):
        # The saved validator accepts the recorded closure; current code hashes
        # must not replace it or force regeneration of old science.
        validated=W.settings_check(self.default)
        for model in W.MODELS:
            c=dict(self.config,detector=model,source=W.CS,primary_count=20)
            recorded={'original-source.py':'a'*64}
            with self.subTest(model=model):
                plan=W.check(c,root=self.root,validate_settings=lambda *_:copy.deepcopy(validated),
                    pin_reader=lambda *_:dict(recorded),runtime_reader=lambda *_:{'python_sha256':'b'*64,'julia_sha256':'c'*64},
                    portable_reader=lambda *_:None)
                before=W.encoded(plan)
                W.saved_plan(plan,self.root)
                self.assertEqual(W.encoded(plan),before)
                self.assertEqual(plan['resolved']['source_sha256'],recorded)
                bad=copy.deepcopy(plan);bad['resolved']['selection']['primary_count']=21
                bad['configuration_sha256']=W.digest(bad['resolved'])
                with self.assertRaises(W.ControlError):W.saved_plan(bad,self.root)


    def test_withheld_attempt_metadata_never_enables_a_source(self):
        registry=copy.deepcopy(W.read(W.ROOT/'scenarios/detector-capabilities.json'))
        source={'id':'fixture_decay','source_contract':{'adapter':D.ADAPTER},'available':False,'reason':'Pending.'}
        registry['source_attempts']={'fixture_decay':{'status':'qualification_withheld','reason':'Trial completed; one below-threshold rejection.'}}
        reader=W.read
        with patch.object(W,'read',side_effect=lambda path:registry if str(path).endswith('detector-capabilities.json') else reader(path)),patch.object(D,'source_catalog',return_value=[source]):
            result=W.catalog()['sources'][0]
        self.assertIs(result['available'],False)
        self.assertEqual(result['reason'],'Trial completed; one below-threshold rejection.')


if __name__=='__main__':unittest.main()
