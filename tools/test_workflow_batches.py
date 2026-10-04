"""M15a pure/injected checks. No radiation, SSD, readout or environment setup."""
import contextlib
import copy
import io
import json
from pathlib import Path
import tempfile
import tracemalloc
import unittest
from unittest.mock import Mock, patch

import workflow_batches as B
import scenario_workflow as W
import local_ui_workflow_jobs as J


class BatchArithmetic(unittest.TestCase):
    def test_exact_disjoint_complete_partition_boundaries(self):
        cases = {1:[1],499:[499],500:[500],9999:[9999],10000:[10000],
                 10001:[10000,1],25001:[10000,10000,5001]}
        for count, sizes in cases.items():
            with self.subTest(count=count):
                p=B.partition(count,26092631);rows=list(B.iter_batches(p))
                self.assertEqual([r['primary_count'] for r in rows],sizes)
                self.assertEqual(sum(r['primary_count'] for r in rows),count)
                next_id=0
                for row in rows:
                    lo,hi=row['global_initial_primary_id_range']
                    self.assertEqual(lo,next_id);next_id=hi+1
                    self.assertEqual(B.global_initial_id(p,row,0),lo)
                    self.assertEqual(B.global_initial_id(p,row,row['primary_count']-1),hi)
                self.assertEqual(next_id,count)
                B.validate_seed_receipts(p,iter(rows))

    def test_numeric_representability_and_seed_capacity_are_distinct(self):
        self.assertEqual(B.primary_count(B.MAX_SAFE_INTEGER),B.MAX_SAFE_INTEGER)
        for n in (0,-1,True,1.0,'1',None,[],B.MAX_SAFE_INTEGER+1):
            with self.subTest(count=n),self.assertRaises(W.ControlError):B.partition(n,1)
        with self.assertRaisesRegex(W.ControlError,'unique radiation-seed limit'):
            B.partition(B.MAX_SEEDED_PRIMARIES+1,1)
        for seed in (0,-1,True,1.0,'1',B.SEED_MAX+1):
            with self.subTest(seed=seed),self.assertRaises(W.ControlError):B.partition(1,seed)

    def test_huge_partition_stays_lazy_and_constant_size(self):
        tracemalloc.start()
        try:
            p=B.partition(B.MAX_SEEDED_PRIMARIES,B.SEED_MAX)
            batches=B.iter_batches(p)
            self.assertIs(iter(batches),batches)
            first=next(batches);last=B.batch_at(p,p['batch_count']-1)
            self.assertEqual(first['radiation_seed'],B.SEED_MAX)
            self.assertEqual(last['global_initial_primary_id_range'][1],B.MAX_SEEDED_PRIMARIES-1)
            self.assertLess(len(W.encoded(p)),1500)
            self.assertLess(tracemalloc.get_traced_memory()[1],100000)
        finally:tracemalloc.stop()

    def test_seed_stability_in_total_name_order_and_terminal_remainder(self):
        p=B.partition(10001,26092631);q=B.partition(25001,26092631)
        for index in (1,0):
            self.assertEqual(B.batch_at(p,index)['radiation_seed'],B.batch_at(q,index)['radiation_seed'])
        self.assertNotEqual(B.batch_at(q,0)['radiation_seed'],B.batch_at(q,1)['radiation_seed'])
        # Bijective modular step admits the entire domain without enumerating it.
        self.assertEqual((B.SEED_STRIDE*pow(B.SEED_STRIDE,-1,B.SEED_MAX))%B.SEED_MAX,1)

    def test_collisions_and_rehashed_rule_or_batch_mutations_refused(self):
        p=B.partition(25001,123);records=list(B.iter_batches(p))
        bad=copy.deepcopy(records);bad[1]['radiation_seed']=bad[0]['radiation_seed']
        for rows in (bad,records[::-1],records[:-1],records+records[:1]):
            with self.assertRaises(W.ControlError):B.validate_seed_receipts(p,iter(rows))
        for field,value in (('seed_stride',0),('batch_cap',20000),('batches_serial',1),
                            ('batch_count',3.0),('primary_count',True),('schema_version',True)):
            changed=copy.deepcopy(p);changed[field]=value
            with self.subTest(field=field),self.assertRaises(W.ControlError):B.validate_partition(changed)
        for field,value in (('primary_count',20000),('radiation_seed',True),('batch_index',1.0),
                            ('global_initial_offset',10001)):
            changed=copy.deepcopy(records[1]);changed[field]=value
            with self.subTest(field=field),self.assertRaises(W.ControlError):B.validate_batch(p,changed)

    def test_raw_row_track_vertex_timing_and_failure_values_are_preserved(self):
        p=B.partition(25001,123);row=B.batch_at(p,2)
        raw={'evtid':0,'raw_row_index':81,'trackid':5,'parent_trackid':2,'vertexid':7,
             'time':500000.125,'edep':0.0,'charge':None,'status':'native_transport_failed',
             'signed_signal':-0.00001,'delayed_groups':[{'group_id':3,'time_ns':999999.5}]}
        before=copy.deepcopy(raw)
        mapped=B.map_raw_record(p,row,raw,file='truth.lh5',table='stp/germanium')
        self.assertEqual(mapped['global_initial_primary_id'],20000)
        self.assertTrue(B.typed_equal(raw,before));self.assertTrue(B.typed_equal(mapped['raw'],before))
        self.assertEqual(mapped['raw_identity'],dict(file='truth.lh5',table='stp/germanium',
            raw_row_index=81,local_initial_primary_id=0))
        mapped['raw']['delayed_groups'][0]['group_id']=9
        self.assertEqual(raw['delayed_groups'][0]['group_id'],3)
        for local in (-1,5001,True,0.0):
            with self.assertRaises(W.ControlError):B.global_initial_id(p,row,local)
        for file in ('../truth.lh5','/truth.lh5','C:/truth.lh5','a//truth.lh5','a\\truth.lh5'):
            with self.assertRaises(W.ControlError):B.map_raw_record(p,row,raw,file=file,table='tracks')

    def test_independent_macro_raw_and_complete_initial_census(self):
        p=B.partition(10001,123);batch=B.batch_at(p,0)
        checked=B.validate_census(p,batch,macro_text='# /run/beamOn 20000\n/run/beamOn 10000 # count\n',
            number_of_simulated_events=10000,initial_ids=iter(range(10000)))
        self.assertEqual(checked['initial_ledger_count'],10000)
        # Same count/ledger must be admitted regardless of Julia thread choices.
        for macro,raw,ids in (('/run/beamOn 20000',20000,range(10000)),
                             ('/run/beamOn 10000',20000,range(20000)),
                             ('/run/beamOn 10000\n/run/beamOn 1',10000,range(10000)),
                             ('/run/beamOn {N}',10000,range(10000)),
                             ('/run/beamOn 10000',10000,range(9999)),
                             ('/run/beamOn 10000',10000,[0,0]),
                             ('/run/beamOn 10000',10000,[1,0]),
                             ('/run/beamOn 10000',10000,[False]),
                             ('/run/beamOn 10000',10000.0,range(10000))):
            with self.assertRaises(W.ControlError):B.validate_census(p,batch,macro_text=macro,
                number_of_simulated_events=raw,initial_ids=iter(ids))
        final=B.batch_at(p,1)
        check=B.validate_census(p,final,macro_text='/run/beamOn 1',number_of_simulated_events=1,initial_ids=iter([0]))
        self.assertEqual(check['global_initial_primary_id_range'],[10000,10000])


class SharedResolver(unittest.TestCase):
    def setUp(self):
        base=W.ROOT/'.local/product-delivery-v1/m15a/implementation';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.config=dict(name='fixture-v2',cryostat=W.CRYOSTAT,detector='AK02',source=W.CS,pose='nominal',
            primary_count=25001,seed=26092631,threads=2,electronics=W.catalog()['electronics_defaults'])
        self.settings=lambda values,root:{'profile':{'schema_version':2,'settings':copy.deepcopy(values)},
            'configuration':dict(values,expected_primary_count=None,max_samples_per_event=500000,max_window_ns=1000000),
            'physics_sha256':W.digest(values)}
        self.readers=dict(validate_settings=self.settings,pin_reader=lambda d,r:{'fixture.txt':'test-only'},
                          runtime_reader=lambda t:{'python_sha256':'test-only','julia_sha256':'test-only'})
        self.request={'kind':B.REQUEST_KIND,'schema_version':2,'selection':self.config}

    def preview(self,config=None):return W.preview(self.config if config is None else config,root=self.root,**self.readers)

    def test_count_source_thread_and_name_variations_keep_v1_frozen(self):
        for source,pose in ((W.CS,'nominal'),(W.GAMMA,'plus5mm')):
            for n in (1,499,500,9999,10000,10001,25001):
                config=dict(self.config,source=source,pose=pose,primary_count=n,seed=42)
                plan=self.preview(config)
                self.assertEqual(plan['resolved']['selection'],config);self.assertFalse(plan['execution_enabled'])
                self.assertEqual(plan['science_calls'],0)
                self.assertEqual(plan['resolved']['batching']['primary_count'],n)
                if source==W.CS and n==500:
                    self.assertEqual(W.check(config,root=self.root,**self.readers,portable_reader=lambda c,r:None)['kind'],W.KIND)
                else:
                    with self.assertRaises(W.ControlError):W.check(config,root=self.root,**self.readers,portable_reader=lambda c,r:None)
        first=self.preview();changed=self.preview(dict(self.config,name='other-name',threads=1))
        self.assertEqual(first['resolved']['batching'],changed['resolved']['batching'])
        self.assertNotEqual(first['configuration_sha256'],changed['configuration_sha256'])
        for detector in W.RINGS:
            p=self.preview(dict(self.config,detector=detector))
            self.assertIn('operating_model',p['resolved'])
            with self.assertRaises(W.ControlError):self.preview(dict(self.config,detector=detector,source=W.GAMMA,pose='plus5mm'))

    def test_preview_and_cli_and_gui_reconstruct_identically_without_writes(self):
        config_path=self.root/'request.json';W.write(config_path,self.request,fresh=True)
        before={p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        original=W.preview
        def resolved(c,root=None):return original(c,root=self.root,**self.readers)
        with patch.object(W,'preview',side_effect=resolved),patch.object(W,'portable_query',side_effect=AssertionError('no process')):
            stdout=io.StringIO()
            with contextlib.redirect_stdout(stdout):W.main(['preview-batches','--config',str(config_path)])
            controller=J.WorkflowController(self.root,launcher=Mock(side_effect=AssertionError('no launch')))
            gui=controller.preview_batches(W.read(config_path));cli=W.decode_json(stdout.getvalue())
            self.assertTrue(B.typed_equal(gui,cli));self.assertNotIn('check_id',gui)
            self.assertEqual(controller._checks,{})
        self.assertEqual(before,{p.relative_to(self.root):p.read_bytes() for p in self.root.rglob('*') if p.is_file()})
        self.assertFalse((self.root/W.BASE).exists());self.assertFalse((self.root/J.STATE).exists())

    def test_start_and_run_refuse_preview_before_lease_state_or_output(self):
        plan=self.preview();controller=J.WorkflowController(self.root,launcher=Mock())
        controller._checks['injected-preview']=plan
        with patch.object(W,'execution_lease',side_effect=AssertionError('lease')),patch.object(W,'write',side_effect=AssertionError('write')):
            with self.assertRaises(W.ControlError):controller.start('injected-preview')
            with self.assertRaises(W.ControlError):W.execute(plan,root=self.root)
        controller._launcher.assert_not_called();self.assertEqual(controller._jobs,[])
        self.assertEqual(list(self.root.iterdir()),[])

    def test_imports_and_rehashed_plan_mutants_refused(self):
        for key,value in (('primary_count',0),('primary_count',True),('primary_count',1.0),
                          ('primary_count',B.MAX_SAFE_INTEGER+1),('primary_count','10001'),
                          ('threads',True),('seed',True),('name','../escape'),('name','CON'),('pose','other')):
            with self.subTest(key=key,value=value),self.assertRaises(W.ControlError):self.preview(dict(self.config,**{key:value}))
        for mutate in (lambda r:r.update(schema_version=True),lambda r:r.update(schema_version=1),
                       lambda r:r.update(extra=True),lambda r:r.update(selection=[]),lambda r:r.pop('kind')):
            request=copy.deepcopy(self.request);mutate(request)
            with self.assertRaises(W.ControlError):self.preview(W.preview_request(request))
        for text in ('{"primary_count":1,"primary_count":2}','{"primary_count":NaN}','{"primary_count":1e999}'):
            with self.assertRaises(ValueError):W.decode_json(text)
        plan=self.preview();self.assertEqual(W.admit_preview(plan,root=self.root,**self.readers),plan)
        for mutate in (lambda r:r['batching'].update(seed_stride=0),lambda r:r['batching'].update(batch_cap=20000),
                       lambda r:r['numerics'].update(bias_V=501),lambda r:r['electronics_configuration'].update(gain=11),
                       lambda r:r['source_sha256'].clear()):
            changed=copy.deepcopy(plan);mutate(changed['resolved']);changed['configuration_sha256']=W.digest(changed['resolved'])
            with self.assertRaises(W.ControlError):W.admit_preview(changed,root=self.root,**self.readers)


if __name__=='__main__':unittest.main()
