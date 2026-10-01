"""M7 SAP22 software acceptance; numerical stages are explicitly mocked.

The source parser starts Julia without loading any simulation module. Public
dry-runs read the real checked inputs with Julia deliberately unavailable.
Actual detector calculations belong to the coordinator's frozen host test.
"""
import argparse
import ast
import copy
from contextlib import nullcontext
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from unittest import mock

import charge_check as C
import group_checkpoints as G
import native_group_checkpoints as N
import native_readout_integration as I
import replay_readout as R
import test_native_group_checkpoints as NF
import test_native_readout_integration as T
import test_replay_readout as RF
import test_group_checkpoints as GF

ROOT=I.ROOT
EVIDENCE=None
SOURCE_NAMES=tuple(sorted(set((*I.SOURCES,'tools/test_native_readout_detector.py',
    'tools/test_native_readout_integration.py','tools/test_native_group_checkpoints.py',
    'tools/test_replay_readout.py','tools/test_group_checkpoints.py',
    'tools/NATIVE_READOUT_INTEGRATION.md'))))
SETTINGS=dict(drift_cap_ns=10000,drift_dt_ns=2,parcels=16,seed_family=2609261,temperature_K=77)


class ModelFixture(T.Fixture):
    """Same prior mock electronics oracle, using the selected model's paths."""
    def electronics_session(self,root,dest,m,mh,runtime,groups,attempt,callback):
        model=m['plan']['model'];scratch=attempt/'mock';scratch.mkdir()
        folder=scratch/'inputs'/model;folder.mkdir(parents=True)
        G.write_bytes(folder/'scalars.jsonl',b''.join(G.encoded(r) for r in I.ledger(dest,m['plan'])))
        data=','.join(C.SIGNAL_COLUMNS)+'\n'
        for g in m['plan']['groups']:
            data+=''.join((dest/'charge'/g['key']/'signals.csv').read_text().splitlines(keepends=True)[1:])
        G.write_bytes(folder/'signals.csv',data.encode())
        report=RF.tiny_worker(scratch,{'detectors':m['detectors']});d=m['detectors'][0]
        if not (dest/'calibration'/model).exists():
            self.calls.append(['MOCK_EXECUTED_CALIBRATION',model]);stage=attempt/('calibration-'+model);stage.mkdir()
            cal=dict(kind='saved_charge_calibration_v1',model=model,config=d['config'],runtime=G.raw_runtime(runtime),
                calibration=report['detectors'][model]['calibration'],calibration_seconds=0.)
            G.write_json(stage/'calibration.json',cal)
            callback(dict(kind='group_ready',phase='calibration',key=model,directory=stage.name))
            if self.after_calibration:raise RuntimeError('MOCK interruption after calibration commit before ACK')
        for g in groups:
            self.calls.append(['MOCK_EXECUTED_ELECTRONICS',g['key']]);stage=attempt/('electronics-'+g['key']);stage.mkdir()
            rec=next(r for r in C.Reader(scratch).jsonl('worker/'+model+'/scalars.jsonl')
                if r['record_kind']=='pulse' and r['event_id']==g['identity']['event_id'])
            traces=[r for r in C.Reader(scratch).jsonl('worker/'+model+'/traces.jsonl') if r['event_id']==rec['event_id']]
            counts=dict.fromkeys(R.COUNT_FIELDS,0);counts.update(groups=1,rejected=1)
            if rec['status']=='native_transport_failed':counts['native_failed_groups']=1
            else:counts.update(readout_rejected=1,native_charge_samples=3,analog_samples=50000)
            cal=NF.read(dest/'calibration'/model/'calibration.json')
            G.write_json(stage/'result.json',dict(kind='saved_charge_electronics_group_v1',key=g['key'],runtime=G.raw_runtime(runtime),
                config=d['config'],calibration_sha256=G.digest_bytes(G.encoded(cal)),counts=counts,electronics_seconds=0.))
            G.write_bytes(stage/'scalars.jsonl',G.encoded(rec));G.write_bytes(stage/'traces.jsonl',b''.join(G.encoded(r) for r in traces))
            callback(dict(kind='group_ready',phase='electronics',key=g['key'],directory=stage.name))
            if self.after_electronics:raise RuntimeError('MOCK interruption after electronic commit before ACK')


class DetectorTests(unittest.TestCase):
    def setUp(self):
        self.home=EVIDENCE/('t-'+G.digest_bytes(self.id().encode())[:8]);self.root=self.home/'r'
        NF.make_fixture(self.root)
        for name in I.SOURCES:
            path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(ROOT/name,path)
        G.write_bytes(self.root/'fixture-runtime.bin',b'MOCK runtime, never executable\n')
        self.f=ModelFixture(self.root);self.dest=self.root/T.BASE/'new'
        self.contract='.local/native-bridge-pilot/contracts-v3/SAP22.json'
        self.prepared='.local/cs137-1m/inputs/SAP22/prepared.json'
        self.cache=N.BATCH+'/cache/SAP22.jls'
        self.include='ADLChargeDriftModel/drift_velocity_config.yaml'
        original=NF.plan_fixture(self.root,'abort');events=copy.deepcopy(original['events'])
        for e,eid in zip(events,[0,207,263]):
            for k in ('event_id','global_decay_id','seed_event_id'):e[k]=eid
            e['identity'].update(model_id='SAP22',local_primary_id=eid,global_primary_id=eid)
            if eid:
                for s in e['steps']:
                    s['raw_row_index']=s['raw']['raw_row_index']=eid;s['raw']['evtid']=eid
                e['pulse_groups'][0]['row_indices']=[eid]
                z=copy.deepcopy(e['steps'][0]);z['energy_keV']=z['raw']['edep']=0.
                z['raw_row_index']=z['raw']['raw_row_index']=eid+1;e['steps'].append(z)
        self.write('models/SAP22.yaml',b'MOCK model, never parsed\n')
        self.write('models/'+self.include,b'MOCK drift include, never parsed\n')
        model_hash=G.digest_bytes((self.root/'models/SAP22.yaml').read_bytes())
        prepared=dict(original['prepared'],model_id='SAP22',model_sha256=model_hash)
        self.put(self.prepared,prepared);self.write(self.cache,b'MOCK SAP22 cache, never deserialized\n')
        include_hash=G.digest_bytes((self.root/'models'/self.include).read_bytes())
        self.put('models/catalog.json',dict(detectors=[dict(id='SAP22',model_sha256=model_hash,readout_contact_id=1,
            dependencies=[self.include],contacts=[dict(id=1,potential_V=0),dict(id=2,potential_V=700)])],
            dependencies=[dict(path=self.include,sha256=include_hash)]))
        contract=dict(kind='selected_native_hdf5_pilot_v1',status='complete',model_id='SAP22',source_sha256={},
            input_sha256={'fixture-input.bin':original['cache_sha256']},prepared=prepared,model_sha256=model_hash,
            events=events,input_population_reference=original['population_reference'],seed_rule=original['seed_rule'])
        self.put(self.contract,contract)
        self.put(N.EXPORT,dict(kind='selected_native_hdf5_pilot_v1',status='exported_checked_inputs',
            contracts={'SAP22':dict(file='SAP22.json',sha256=self.hash(self.contract))},
            source_sha256=contract['source_sha256'],input_sha256=contract['input_sha256']))
        self.put(N.BATCH+'/config.json',dict(kind='native_checkpoint_batch_v1',settings=SETTINGS,
            models={'SAP22':dict(prepared=prepared,cache_file='cache/SAP22.jls',cache_sha256=self.hash(self.cache),expected_field_fingerprint={})},
            source_sha256={n:self.hash(n) for n in N.NUMERICAL},
            expected_environment=dict(environment_manifest_sha256=self.hash('simulation/Manifest.toml'))))
        self.write(N.BATCH+'/config.sha256',self.hash(N.BATCH+'/config.json').encode())
        self.specs=copy.deepcopy(N.INTEGRATION_DETECTORS)
        self.specs['SAP22'].update(contract_sha256=self.hash(self.contract),model_sha256=model_hash,
            prepared_sha256=self.hash(self.prepared),cache_sha256=self.hash(self.cache),dependencies={self.include:include_hash})
        self.batch_hash=self.hash(N.BATCH+'/config.json');self.catalog_hash=self.hash('models/catalog.json')
        self.simulation_before=NF.snapshot(self.root/'simulation')

    def tearDown(self):self.assertEqual(NF.snapshot(self.root/'simulation'),self.simulation_before)
    def hash(self,name):return G.digest_bytes((self.root/name).read_bytes())
    def put(self,name,value):self.write(name,G.encoded(value))
    def write(self,name,data):
        path=self.root/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    def read(self,name):return NF.read(self.root/name)

    def run_product(self,**kwargs):
        def profile(reader,path):
            p=reader.json(path);config=R.expected_config(reader,p,3)
            return dict(mocked_profile_dispatch=True,profile=p,configuration=dict(config,expected_primary_count=None)),None
        with mock.patch.object(I,'BASE',T.BASE),mock.patch.object(R,'resolve_profile',side_effect=profile),\
            mock.patch.object(N,'INTEGRATION_DETECTORS',self.specs),\
            mock.patch.object(N,'INTEGRATION_BATCH_SHA256',self.batch_hash),\
            mock.patch.object(N,'INTEGRATION_CATALOG_SHA256',self.catalog_hash),\
            mock.patch.object(N,'probe_runtime',side_effect=self.f.native_probe),\
            mock.patch.object(I,'probe_readout',side_effect=self.f.readout_probe),\
            mock.patch.object(N,'run_session',side_effect=self.f.native_session),\
            mock.patch.object(G,'run_session',side_effect=self.f.electronics_session):
            return I.integrate(self.root,kwargs.pop('name','new'),**kwargs)

    def new(self,**kwargs):return self.run_product(detector='SAP22',**kwargs)
    def refuse(self,**kwargs):
        before=NF.snapshot(self.root);self.f.calls=[];result=self.run_product(**kwargs)
        self.assertEqual(result['status'],'blocked',result);self.assertFalse(result['verification_final'])
        self.assertEqual(self.f.calls,[]);self.assertEqual(NF.snapshot(self.root),before);return result
    def rehash_batch(self):self.write(N.BATCH+'/config.sha256',self.hash(N.BATCH+'/config.json').encode())
    def rebind_manifest(self):
        initial=self.read(T.BASE+'/new/INITIAL.json')
        initial['manifest']=G.stamps(C.Reader(self.dest),['manifest.json'])['manifest.json']
        self.put(T.BASE+'/new/INITIAL.json',initial)

    def test_sap22_dryrun_exact_selection_no_output_or_probe(self):
        before=NF.snapshot(self.root);r=self.new(dry_run=True)
        self.assertEqual(r['status'],'planned',r);self.assertEqual(self.f.calls,[])
        self.assertEqual(NF.snapshot(self.root),before);self.assertFalse(self.dest.exists())
        self.assertEqual(r['selected_census'],dict(initial_primaries=3,zero_ge_primaries=1,nonzero_primaries=2,groups=2))

    def test_sap22_full_model_keys_whole_rows_signed_flags_fixed_calibration(self):
        r=self.new();self.assertEqual(r['status'],'completed',r)
        m=self.read(T.BASE+'/new/manifest.json');plan=m['plan'];d=m['detectors'][0]
        self.assertEqual(plan['selected_primary_ids'],[0,207,263]);self.assertEqual(plan['events'],self.read(self.contract)['events'])
        self.assertEqual(plan['detector_settings'],dict(model_id='SAP22',source_temperature_K=78,temperature_K=77,bias_V=700,readout_contact_id=1))
        self.assertEqual(I.expected(plan)['calibration'],['SAP22']);self.assertTrue(all(g['key'].startswith('SAP22-') for g in plan['groups']))
        self.assertEqual(set(r['detectors']),{'SAP22'});self.assertEqual(G.inventory(self.dest/'worker'),['SAP22/scalars.jsonl','SAP22/traces.jsonl','report.json'])
        rows=list(C.Reader(self.dest).jsonl('worker/SAP22/scalars.jsonl'))
        self.assertEqual([x['event_id'] for x in rows if x['record_kind']=='decay'],[0,207,263])
        self.assertEqual(sum(s['energy_keV']==0 for e in plan['events'] for s in e['steps']),2)
        self.assertTrue(all(x['readout']['negative_input'] and x['transport_flags']['stopped_without_contact']==32 for x in rows if x['record_kind']=='pulse'))
        expected=R.expected_config(C.Reader(self.root),d['profile'],1)
        self.assertEqual({k:v for k,v in d['config'].items() if k!='expected_primary_count'},
                         {k:v for k,v in expected.items() if k!='expected_primary_count'})
        self.assertEqual([c for c in self.f.calls if isinstance(c,list) and c[0]=='MOCK_EXECUTED_CALIBRATION'],[['MOCK_EXECUTED_CALIBRATION','SAP22']])

    def test_sap22_selected_order_is_saved_and_completed_resume_readonly(self):
        r=self.new(primary_ids='263,0,207');self.assertEqual(r['status'],'completed',r)
        m=self.read(T.BASE+'/new/manifest.json');self.assertEqual(m['plan']['selected_primary_ids'],[263,0,207])
        before=NF.snapshot(self.dest);self.f.calls=[]
        with mock.patch.dict(os.environ,JULIA_EXE='INVALID_NO_JULIA'):
            for dry in (False,True):
                r=self.run_product(resume=True,dry_run=dry);self.assertTrue(r['idempotent'],r)
        self.assertEqual(self.f.calls,[]);self.assertEqual(NF.snapshot(self.dest),before)

    def test_sap22_charge_death_electronics_pause_resume_no_recalibration(self):
        self.f.after_native=True;self.assertEqual(self.new()['status'],'failed');protected=T.durable(self.dest)
        self.f.after_native=False;self.f.calls=[]
        self.assertEqual(self.run_product(resume=True,stop_after_groups=1)['status'],'paused')
        T.assert_preserved(self.dest,protected)
        self.assertEqual(len([c for c in self.f.calls if isinstance(c,list) and c[0]=='MOCK_EXECUTED_NATIVE']),1)
        protected=T.durable(self.dest);self.f.calls=[]
        self.assertEqual(self.run_product(resume=True)['status'],'completed');T.assert_preserved(self.dest,protected)
        self.assertFalse(any(c=='MOCK_NATIVE_PROBE' or isinstance(c,list) and c[0] in ('MOCK_EXECUTED_NATIVE','MOCK_EXECUTED_CALIBRATION') for c in self.f.calls))

    def test_sap22_calibration_pre_ack_failure_reuses_committed_calibration(self):
        self.f.after_calibration=True;self.assertEqual(self.new()['status'],'failed');protected=T.durable(self.dest)
        self.f.after_calibration=False;self.f.calls=[]
        self.assertEqual(self.run_product(resume=True)['status'],'completed');T.assert_preserved(self.dest,protected)
        self.assertFalse(any(isinstance(c,list) and c[0] in ('MOCK_EXECUTED_NATIVE','MOCK_EXECUTED_CALIBRATION') for c in self.f.calls))

    def test_unsupported_detector_refuses_before_plan(self):
        for detector in ('both','AK01','sap22','SAP22 ', '',None,17,True):
            if detector is None:continue
            with self.subTest(detector=detector):self.refuse(detector=detector)

    def test_every_explicit_resume_detector_and_primary_override_refuses(self):
        self.assertEqual(self.new(stop_after_groups=1)['status'],'paused')
        for detector in ('SAP22','AK02','both',''):
            with self.subTest(detector=detector):self.refuse(resume=True,detector=detector)
        for ids in ('0,207,263','263,0,207',''):
            with self.subTest(ids=ids):self.refuse(resume=True,primary_ids=ids)

    def test_missing_or_corrupted_calibration_receipt_refuses(self):
        self.assertEqual(self.new(stop_after_groups=1)['status'],'paused')
        (self.dest/'receipts/calibration/SAP22.json').write_bytes(b'{}\n');self.refuse(resume=True)

    def test_unbound_manifest_detector_never_reaches_detector_selection(self):
        self.assertEqual(self.new(stop_after_groups=1)['status'],'paused')
        m=self.read(T.BASE+'/new/manifest.json');m['plan']['model']='AK02';self.put(T.BASE+'/new/manifest.json',m)
        with mock.patch.object(N,'integration_detector',side_effect=AssertionError('Unbound detector was read')):
            result=self.refuse(resume=True)
        self.assertNotIn('Unbound detector was read',str(result))

    def test_rehashed_manifest_detector_contact_and_bias_refused(self):
        self.assertEqual(self.new(stop_after_groups=1)['status'],'paused')
        m=self.read(T.BASE+'/new/manifest.json');m['plan']['detector_settings']['bias_V']=500
        self.put(T.BASE+'/new/manifest.json',m);self.rebind_manifest();self.refuse(resume=True)

    def test_rehashed_manifest_generated_electronics_config_refused(self):
        self.assertEqual(self.new(stop_after_groups=1)['status'],'paused')
        m=self.read(T.BASE+'/new/manifest.json');m['detectors'][0]['config']['adc_bits']-=1
        self.put(T.BASE+'/new/manifest.json',m);self.rebind_manifest();self.refuse(resume=True)

    def test_independently_rehashed_batch_settings_refuse(self):
        c=self.read(N.BATCH+'/config.json');c['settings']['temperature_K']=78
        self.put(N.BATCH+'/config.json',c);self.rehash_batch();self.refuse(detector='SAP22',dry_run=True)

    def test_rehashed_swapped_cache_path_and_hash_refuse(self):
        c=self.read(N.BATCH+'/config.json');self.write(N.BATCH+'/cache/AK02.jls',b'MOCK wrong model cache\n')
        c['models']['SAP22'].update(cache_file='cache/AK02.jls',cache_sha256=self.hash(N.BATCH+'/cache/AK02.jls'))
        self.put(N.BATCH+'/config.json',c);self.rehash_batch();self.refuse(detector='SAP22',dry_run=True)

    def test_cache_bytes_refuse_without_probe(self):
        self.write(self.cache,b'MOCK replaced cache\n');self.refuse(detector='SAP22',dry_run=True)

    def test_swapped_model_bytes_refuse_without_probe(self):
        self.write('models/SAP22.yaml',b'MOCK AK02 model\n');self.refuse(detector='SAP22',dry_run=True)

    def test_rehashed_export_contract_cannot_change_model_or_event_identity(self):
        d=self.read(self.contract);d['events'][1]['identity']['model_id']='AK02';self.put(self.contract,d)
        export=self.read(N.EXPORT);export['contracts']['SAP22']['sha256']=self.hash(self.contract);self.put(N.EXPORT,export)
        self.refuse(detector='SAP22',dry_run=True)

    def test_original_prepared_detector_refuses(self):
        p=self.read(self.prepared);p['model_id']='AK02';self.put(self.prepared,p)
        self.refuse(detector='SAP22',dry_run=True)

    def test_catalog_contact_refuses_independently_of_rehashed_inputs(self):
        c=self.read('models/catalog.json');c['detectors'][0]['readout_contact_id']=2
        self.put('models/catalog.json',c);self.refuse(detector='SAP22',dry_run=True)

    def test_rehashed_catalog_include_hash_cannot_adopt_changed_include(self):
        self.write('models/'+self.include,b'MOCK changed drift include\n')
        c=self.read('models/catalog.json');c['dependencies'][0]['sha256']=self.hash('models/'+self.include)
        self.put('models/catalog.json',c);self.refuse(detector='SAP22',dry_run=True)

    def test_missing_changed_include_refuses(self):
        self.write('models/'+self.include,b'MOCK changed drift include\n');self.refuse(detector='SAP22',dry_run=True)

    def test_unique_safe_catalog_dependency_lookup(self):
        c=self.read('models/catalog.json');entry=c['detectors'][0]
        self.assertEqual(N.model_dependencies(C.Reader(self.root),c,entry),self.specs['SAP22']['dependencies'])
        c['dependencies'].append(copy.deepcopy(c['dependencies'][0]))
        with self.assertRaises(C.Rejected):N.model_dependencies(C.Reader(self.root),c,entry)
        for name in ('../escape.yaml','/root.yaml','C:/private.yaml','x//file.yaml','x\\file.yaml'):
            with self.subTest(name=name),self.assertRaises(C.Rejected):N.model_dependencies(C.Reader(self.root),c,dict(dependencies=[name]))

    def test_wrong_model_and_raw_alias_full_ledger_checks(self):
        d=self.read(self.contract)
        for mutation in ('model','seed','clock','zero_row'):
            events=copy.deepcopy(d['events'])
            if mutation=='model':events[1]['identity']['model_id']='AK02'
            elif mutation=='seed':events[1]['seed_event_id']+=1
            elif mutation=='clock':events[1]['steps'][0]['time_ns']+=1
            else:events[1]['steps'][-1]['raw']['edep']=1.
            with self.subTest(mutation=mutation),self.assertRaises(C.Rejected):N.expected_groups(events,d['prepared'],'SAP22')
        with self.assertRaises(C.Rejected):N.expected_groups(d['events'],d['prepared'])

    def test_unknown_zero_only_duplicate_selection_refuses(self):
        for ids in ('0','0,999999','0,207,207','0207,263','207,263 ', '0,1,2,3,4,5,6,7,8'):
            with self.subTest(ids=ids):self.refuse(detector='SAP22',primary_ids=ids,dry_run=True)

    def test_actual_checked_plans_default_ak02_and_sap22_whole_census(self):
        before={name:NF.snapshot(ROOT/name) for name in ('models','simulation')}
        ak,_,_=I.load_plan(C.Reader(ROOT));sap,d,_=I.load_plan(C.Reader(ROOT),detector='SAP22')
        self.assertEqual(ak['model'],'AK02');self.assertEqual(ak['selected_primary_ids'],[0,2594,3950])
        self.assertNotIn('detector_selection_mode',ak);self.assertNotIn('detector_settings',ak)
        self.assertEqual(sap['selected_primary_ids'],[0,207,263]);self.assertEqual(d['model'],'SAP22')
        self.assertEqual(sum(len(e['steps']) for e in sap['events']),33)
        self.assertEqual(sum(s['energy_keV']>0 for e in sap['events'] for s in e['steps']),29)
        self.assertEqual(sum(s['energy_keV']==0 for e in sap['events'] for s in e['steps']),4)
        self.assertEqual([g['key'] for g in sap['groups']],['SAP22-e207-d207-g0','SAP22-e263-d263-g0'])
        for e in sap['events']:self.assertEqual(e['identity']['radiation_seed'],996008157)
        self.assertEqual(before,{name:NF.snapshot(ROOT/name) for name in ('models','simulation')})

    def test_public_detector_dispatch_readonly_without_julia(self):
        name='m7fixture-dispatch';dest=ROOT/I.BASE/name;self.assertFalse(dest.exists())
        env=dict(os.environ,JULIA_EXE='INVALID_NO_JULIA',SITE_PYTHON=sys.executable)
        cases=[(['-Detector','SAP22'],0),(['-Detector','SAP22','-PrimaryIds','263,0,207'],0),
            (['-Detector','AK02'],0),([],0),(['-Detector','both'],1),(['-Detector','AK01'],1),
            (['-Detector','SAP22','-Resume'],1),(['-Detector','SAP22','-PrimaryIds','0'],2)]
        for index,(options,expected) in enumerate(cases):
            argv=T.public_command(['native-readout','-Name',name,'-DryRun','-Json',*options])
            result=subprocess.run(argv,cwd=ROOT,env=env,capture_output=True,text=True,timeout=60)
            NF.save(self.home/('dispatch-'+str(index)+'.json'),dict(arguments=argv,exit_code=result.returncode,
                stdout=result.stdout,stderr=result.stderr,actual_host=False))
            self.assertEqual(result.returncode,expected,result.stdout+result.stderr);self.assertFalse(dest.exists())
            if expected==0:
                r=C.decode(next(line for line in result.stdout.splitlines() if line.startswith('{')))
                self.assertEqual(r['status'],'planned');self.assertEqual(r['scientific_workers_launched'],0)

    def test_julia_opt_in_model_cache_bias_boundary_and_parser(self):
        text=(ROOT/'simulation/native_groups.jl').read_text();adapter=(ROOT/I.WORKER).read_text()
        self.assertIn('allow_detector_selection=false',text);self.assertIn('allow_detector_selection=true',adapter)
        self.assertLess(text.index('integration_detector(plan,allow_detector_selection)'),text.index('sim=deserialize('))
        self.assertIn('Declared legacy AK02 model',text);self.assertIn('Declared tiny AK02 cohort',text)
        self.assertIn('Frozen detector cache identity',text);self.assertIn('Cached bias changed',text)
        self.assertIn('Q.parse_args(["--model",model',text)
        for name in ('tools/native_group_checkpoints.py','tools/native_readout_integration.py','tools/test_native_readout_detector.py'):
            ast.parse((ROOT/name).read_text())
        locations=NF.read(ROOT/'.local/m5-close-v1/runtime-locations.json')
        script='''function checktree(x)
    x isa Expr || return
    x.head in (:error,:incomplete) && error(string(x))
    foreach(checktree,x.args)
end
for path in ARGS
    checktree(Meta.parseall(read(path,String)))
    println("PARSED "*basename(path))
end
'''
        path=self.home/'parse.jl';path.write_text(script,encoding='utf-8')
        argv=[locations['julia'],'--startup-file=no','--threads=1',str(path),
            str(ROOT/'simulation/native_groups.jl'),str(ROOT/I.WORKER)]
        result=subprocess.run(argv,cwd=ROOT,capture_output=True,text=True,timeout=60)
        NF.save(self.home/'parser.json',dict(arguments=argv,exit_code=result.returncode,stdout=result.stdout,
            stderr=result.stderr,actual_host=False,numerical_modules_loaded=False))
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)
        self.assertEqual(result.stdout.splitlines(),['PARSED native_groups.jl','PARSED native_readout_groups.jl'])


def legacy_suite(home):
    NF.EVIDENCE=home/'n';GF.EVIDENCE=home/'g';RF.EVIDENCE=home/'r'
    for path in (NF.EVIDENCE,GF.EVIDENCE,RF.EVIDENCE):path.mkdir()
    cases=[(NF.Tests,('test_pause_resume_full_signed_and_zero_ledger_noop','test_known_failure_nulls_explicit_record',
        'test_rehashed_charge_refused','test_duplicate_worker_event_strict','test_read_only_new_and_saved_dryrun',
        'test_valid_commit_ahead_of_progress_reused_without_generation','test_removed_progress_keys_and_hidden_commit_refused',
        'test_held_lease_and_failure_release')),
        (GF.GroupTests,('test_stop_resume_completed_noop_and_calibration_reuse','test_signed_zero_and_failed_native_population',
        'test_new_public_dryrun_no_write_no_julia','test_invalid_flags_and_explicit_profile_overrides')),
        (RF.ReplayTests,('test_public_dryrun_no_write_no_julia','test_unrelated_public_flags_and_missing_name_rejected'))]
    return unittest.TestSuite(cls(name) for cls,names in cases for name in names)


def main(argv=None):
    global EVIDENCE
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--evidence',required=True)
    p.add_argument('--suite',choices=('new','integration','legacy'),default='new')
    p.add_argument('--test',help='One existing integration fixture; source-only focused repair check')
    args=p.parse_args(argv)
    C.require(args.test is None or args.suite=='integration','focused test requires integration suite')
    home=(ROOT/args.evidence).resolve()
    C.require(home.is_relative_to(ROOT/'.local/m7-sap22-v1/software'),'new M7 software evidence only')
    home.mkdir(parents=True,exist_ok=False);EVIDENCE=home
    sources=G.stamps(C.Reader(ROOT),SOURCE_NAMES)
    if args.suite=='integration':
        T.EVIDENCE=home
        suite=unittest.TestSuite([T.Tests(args.test)]) if args.test else unittest.defaultTestLoader.loadTestsFromTestCase(T.Tests)
    elif args.suite=='legacy':suite=legacy_suite(home)
    else:suite=unittest.defaultTestLoader.loadTestsFromTestCase(DetectorTests)
    # The tool shell supplies PowerShell7 paths. WindowsPowerShell children of
    # pvpython do not normalize them, unlike an interactive shell launch. This
    # test-local setting selects existing Windows modules; no installation or
    # persistent user/system variable changes occur.
    modules=str(Path(os.environ['SystemRoot'])/'system32/WindowsPowerShell/v1.0/Modules')
    # The reused source-freeze fixture authorizes only its historical evidence
    # root. Temporarily redirect that TEST helper to this new M7 fixture root.
    # Product guards and historical receipts/sources are never modified/adopted.
    freeze_fixture=mock.patch.object(T,'HOME',home) if args.suite=='integration' else nullcontext()
    with mock.patch.dict(os.environ,PSModulePath=modules),freeze_fixture:
        with (home/'tests.log').open('w',encoding='utf-8') as log:
            result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    G.check_stamps(C.Reader(ROOT),sources)
    record=dict(tests=result.testsRun,errors=len(result.errors),failures=len(result.failures),suite=args.suite,
        source_stamps=sources,actual_host=False,mocked_native=True,mocked_electronics=True,
        Julia_parser_only=args.suite=='new',Julia_simulation_loading_established=False,
        preserved_old_evidence=True,python=sys.version,executable=sys.executable,
        test_child_environment=dict(PSModulePath=modules),persistent_environment_changed=False,
        focused_test=args.test,reused_freeze_fixture_home=str(home) if args.suite=='integration' else None,
        fixture_home_restored=True,product_freeze_guard_changed=False,prior_receipts_adopted=False)
    NF.save(home/'RESULT.json',record)
    print(json.dumps({k:record[k] for k in ('suite','tests','errors','failures','actual_host')}))
    return 0 if result.wasSuccessful() else 1


if __name__=='__main__':sys.exit(main())
