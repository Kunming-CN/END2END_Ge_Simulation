"""Frozen campaign, durable chunks and detached lifecycle with mock science only."""
import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock,patch

import gegi_campaign as C
from gegi_event_store import Store


class FakeTransport:
    def __init__(self):self.calls=[]
    def process(self,folder,selection,tick):
        self.calls.append(selection['name']);folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
        C.write(folder/'selection.json',selection)
        target=folder/'transport';stream=target/'stream';stream.mkdir(parents=True)
        raw=target/'truth.lh5';raw.write_bytes(b'SYNTHETIC RAW TRANSPORT\x00'+selection['name'].encode())
        C.write(target/'prepared.json',{'selection':selection})
        for name in ('geometry.gdml','run.mac'):(target/name).write_bytes(b'SYNTHETIC FIXTURE INPUT')
        event={'event_id':selection['primary_count']-1,'steps':[{'raw_row_index':17,'time_ns':0.,'energy_keV':1.}]}
        (stream/'events.jsonl').write_bytes(C.W.encoded(event)+b'\n')
        counts={'initial_primaries':selection['primary_count'],'zero_deposit_primaries':selection['primary_count']-1,'nonzero_primaries':1}
        C.write(target/'run.json',{'kind':'gegi_transport_run_v1','status':'complete',
                                  'source_lh5_sha256':C.sha(raw),'prepared_sha256':C.sha(target/'prepared.json'),'counts':counts})
        source={'id':selection['source'],'position_global_mm':selection['source_position_mm']}
        if selection['source']==C.GAMMA:source['energy_keV']=selection['gamma_energy_keV']
        C.write(stream/'manifest.json',{'kind':'gegi_event_stream_v1','status':'complete',
            'primary_count':selection['primary_count'],'zero_deposit_primaries':counts['zero_deposit_primaries'],
            'nonzero_primaries':1,'counts':counts,'model_sha256':C.MODEL_SHA,
            'source_id':selection['source'],'source_contract':source,'source_count_unit':C.UNITS[selection['source']],
            'seed':selection['seed'],'events_file':'events.jsonl','events_sha256':C.sha(stream/'events.jsonl'),'source_lh5_sha256':C.sha(raw),
            'prepared_sha256':C.sha(target/'prepared.json'),'geometry_sha256':C.sha(target/'geometry.gdml'),
            'macro_sha256':C.sha(target/'run.mac')})
        tick();return stream/'manifest.json'


class FakeWorker:
    def __init__(self,request,spool,*,after=None):
        self.request=C.read(request);self.request_sha256=C.sha(request)
        self.spool=Path(spool);self.calls=[];self.closed=False;self.after=after
    def start(self):
        return {'new_field_solve':False,'field_cache_sha256':self.request['field_cache']['sha256']}
    def run_chunk(self,manifest_path,store_path,store_identity,*,calibration,photopeak_windows,receipt_path):
        self.calls.append(str(manifest_path));manifest=C.read(manifest_path);n=manifest['primary_count']
        counts={'initial_primaries':n,'zero_deposit_primaries':n-1,'nonzero_primaries':1,
                'pulse_groups':1,'native_failed_groups':1,'imaging_accepted_groups':0,
                'line_photon_counts':{'fixture-line':n}}
        # Explicit native failure fixture: unknown signals remain null.
        event={'event_id':n-1,'group_id':0,'status':'native_failed','channels':None,
               'error':'synthetic native failure retained'}
        response={'kind':C.RESPONSE_KIND,'status':'completed_with_native_failures',
                  'input_manifest_sha256':C.sha(manifest_path),'store_identity_sha256':C.digest(store_identity),
                  'counts':counts,'calibration_sha256':calibration['sha256'],
                  'photopeak_windows_sha256':C.digest(photopeak_windows),
                  'native_request_sha256':self.request_sha256,'new_field_solve':False,'source_id':manifest['source_id']}
        store=Store(store_path,store_identity,create=True)
        try:
            store.append(n-1,0,event,None,C.digest(event));store.seal(response)
        finally:store.close()
        C.write(receipt_path,response,fresh=True)
        if self.after:self.after()
        return response
    def close(self):self.closed=True


class CampaignTests(unittest.TestCase):
    def setUp(self):
        disk_patch=patch.object(C,'available_disk_bytes',return_value=10**15)
        self.disk=disk_patch.start();self.addCleanup(disk_patch.stop)
        self.temp=tempfile.TemporaryDirectory(prefix='gegi-campaign-test-',dir=C.ROOT/'.local')
        self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name);(self.root/'.local').mkdir()
        for ref in C.SOURCES:
            path=self.root/ref;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(b'SYNTHETIC TEST SOURCE\n')
        (self.root/'models/GeGI_3D.yaml').write_bytes((C.ROOT/'models/GeGI_3D.yaml').read_bytes())
        self.inputs=self.root/'.local/inputs';self.inputs.mkdir()
        fields=self.inputs/'fields.jls';fields.write_bytes(b'SYNTHETIC CACHE; NEVER LOADED')
        calibration=self.inputs/'depth-calibration.json'
        C.write(calibration,{'kind':'gegi_pixel_simulated_depth_v1','per_pixel_calibration':True,'synthetic_test':True})
        request=self.inputs/'request.json'
        C.write(request,{'kind':'gegi_campaign_response_request_v1','model_sha256':C.MODEL_SHA,
                         'source_sha256':{},'numerics':{'field_policy':'reuse-only'},'pulse_group_horizon_ns':100000.,
                         'field_cache':{'ref':self.ref(fields),'sha256':C.sha(fields),'model_sha256':C.MODEL_SHA}})
        self.plan=C.draft()
        for index,group in enumerate(self.plan['groups']):
            group['primary_count']=2 if index==0 else 1
            group['partition']=C.B.partition(group['primary_count'],group['master_seed'])
        self.plan['total_initial_primaries']=5
        self.plan['native_request']=self.binding(request);self.plan['calibration']=self.binding(calibration)
        self.acceptance=self.pilots(self.plan)
        self.plan['resource_budget']=C.budget_from_acceptance(self.plan,self.acceptance,multiplier=2.,root=self.root)
        self.directory=self.root/'.local/campaign'
        self.workers=[]

    def ref(self,path):return Path(path).relative_to(self.root).as_posix()
    def binding(self,path):return {'ref':self.ref(path),'sha256':C.sha(path)}

    def pilots(self,plan):
        records=[]
        for group in plan['groups']:
            folder=self.inputs/('pilot-'+group['id'])
            spec=C.pilot_spec(plan,group['id'],1,group['master_seed'])
            manifest=FakeTransport().process(folder,spec['selection'],lambda:None)
            counts={'initial_primaries':1,'zero_deposit_primaries':0,'nonzero_primaries':1,'pulse_groups':1,'native_failed_groups':0}
            transport=folder/'transport/run.json';response=folder/'response.json'
            C.write(transport.parent/'checked-plan.json',{'selection':spec['selection'],
                'runtime':{'synthetic_test':'locked transport runtime'},
                'decay_data':None if group['source']==C.GAMMA else {'synthetic_test_source':group['source']}})
            C.write(transport.parent/'emlow-data.json',{'synthetic_test':'same locked EMLOW bytes','hash_wall_s':1.})
            C.write(transport.parent/'prepared.json',{'selection':spec['selection'],'files_sha256':{
                name:C.sha(transport.parent/name) for name in ('checked-plan.json','emlow-data.json')}})
            receipt=C.read(transport);receipt['prepared_sha256']=C.sha(transport.parent/'prepared.json')
            C.write(transport,receipt)
            meta=C.read(manifest);meta['prepared_sha256']=receipt['prepared_sha256'];C.write(manifest,meta)
            result={'kind':C.RESPONSE_KIND,'status':'completed','counts':counts,
                              'input_manifest_sha256':C.sha(manifest),'calibration_sha256':plan['calibration']['sha256'],
                              'native_request_sha256':plan['native_request']['sha256'],'new_field_solve':False,
                              'store_identity_sha256':C.digest(spec['store_identity']),
                              'electronics_replay':{'status':'verified_exact','drift_executed':False},
                              'photopeak_windows_sha256':C.digest(group['photopeak_windows'])}
            store_path=folder/'events.sqlite';store=Store(store_path,spec['store_identity'],create=True)
            try:
                event={'event_id':0,'group_id':0,'status':'completed','channels':[],'synthetic_test':True}
                store.append(0,0,event,{},C.digest(event));store.seal(result)
            finally:store.close()
            C.write(response,result)
            timing=folder/'timings.json'
            C.write(timing,{'transport_driver_wall_s':.01,'native_response_and_store_wall_s':.02,'synthetic_test':True})
            records.append({'source_group':group['id'],'initial_primaries':1,
                            'transport_receipt':self.binding(transport),'response_receipt':self.binding(response),
                            'store':self.binding(store_path),'timings':self.binding(timing),**C.pilot_storage_bytes(folder)})
        path=self.inputs/'acceptance.json'
        C.write(path,{'kind':C.ACCEPTANCE_KIND,'status':'passed','physics_sha256':C.physics_sha256(plan),'groups':records,
                      'synthetic_test':True})
        return self.binding(path)

    def freeze(self):return C.freeze(self.directory,self.plan,self.acceptance,root=self.root)

    def factory(self,*args,**kwargs):
        worker=FakeWorker(*args,**kwargs);self.workers.append(worker);return worker

    def test_requested_draft_has_exact_10m_1000_bounded_unique_seed_chunks(self):
        plan=C.validate_plan(C.draft());chunks=list(C.chunks(plan))
        self.assertEqual(plan['status'],'draft');self.assertEqual(plan['total_initial_primaries'],10000000)
        self.assertEqual(len(chunks),1000);self.assertEqual(sum(c['batch']['primary_count'] for c in chunks),10000000)
        self.assertEqual(len({c['batch']['radiation_seed'] for c in chunks}),1000)
        self.assertEqual([g['primary_count'] for g in plan['groups']],[2000000,2000000,3000000,3000000])
        self.assertEqual(plan['groups'][2]['photopeak_windows'],plan['groups'][3]['photopeak_windows'])
        self.assertEqual([w['line_energy_keV'] for w in plan['groups'][2]['photopeak_windows']],
                         [661.657,1173.228,1332.492])
        with self.assertRaisesRegex(ValueError,'frozen'):C.validate_plan(plan,frozen=True)
        for edit in (lambda p:p.update(total_initial_primaries=9999999),
                     lambda p:p['groups'][2].update(count_unit='emitted gamma'),
                     lambda p:p['groups'][3].update(gamma_energy_keV=662.),
                     lambda p:p['groups'][2].update(photopeak_windows=p['groups'][2]['photopeak_windows'][:1]),
                     lambda p:p['groups'][1].update(master_seed=p['groups'][0]['master_seed'],partition=p['groups'][0]['partition'])):
            changed=copy.deepcopy(plan);edit(changed)
            with self.assertRaises(ValueError):C.validate_plan(changed)

    def test_freeze_requires_actual_matching_bounded_acceptance_and_exact_cache(self):
        plan=self.freeze();self.assertEqual(C.read_plan(self.directory,root=self.root),plan)
        acceptance_path=self.root/self.acceptance['ref'];accepted=C.read(acceptance_path)
        accepted['status']='not_accepted';C.write(acceptance_path,accepted)
        with self.assertRaisesRegex(ValueError,'Frozen artifact changed'):C.read_plan(self.directory,root=self.root)
        accepted['status']='passed';accepted['physics_sha256']='0'*64;C.write(acceptance_path,accepted)
        with self.assertRaisesRegex(ValueError,'bounded acceptance'):
            C.freeze(self.root/'.local/other',self.plan,self.binding(acceptance_path),root=self.root)
        self.assertFalse((self.root/'.local/other').exists())
        (self.inputs/'fields.jls').write_bytes(b'CHANGED CACHE')
        with self.assertRaisesRegex(ValueError,'Frozen artifact changed'):C.verify_inputs(plan,self.root)

    def test_acceptance_builder_derives_artifact_counts_and_preserves_failed_inputs(self):
        specs=[{'source_group':g['id'],'folder':self.ref(self.inputs/('pilot-'+g['id'])),
                'timings':self.ref(self.inputs/('pilot-'+g['id'])/'timings.json')} for g in self.plan['groups']]
        output=self.inputs/'derived-acceptance.json'
        result=C.build_acceptance(self.plan,specs,output,root=self.root)
        self.assertEqual(result['status'],'passed');self.assertEqual(len(result['groups']),4)
        self.assertTrue(all(g['initial_primaries']==1 and g['retained_artifact_bytes']>0 for g in result['groups']))
        self.assertEqual(result['groups'][0]['response_counts']['pulse_groups'],1)
        (self.inputs/'pilot-gamma-left/transport/truth.lh5').write_bytes(b'changed raw fixture')
        with self.assertRaisesRegex(ValueError,'transport/stream inputs changed'):
            C.build_acceptance(self.plan,specs,self.inputs/'refused.json',root=self.root)
        self.assertFalse((self.inputs/'refused.json').exists())

    def test_frozen_measured_budget_gates_freeze_and_launch_for_remaining_bytes(self):
        no_budget=copy.deepcopy(self.plan);no_budget['resource_budget']=None
        with self.assertRaisesRegex(ValueError,'resource budget missing'):
            C.freeze(self.directory,no_budget,self.acceptance,root=self.root)
        insufficient=copy.deepcopy(self.plan);insufficient['resource_budget']['projected_retained_bytes']=1
        with self.assertRaisesRegex(ValueError,'below measured pilot scaling'):
            C.freeze(self.directory,insufficient,self.acceptance,root=self.root)
        required=C.required_launch_disk_bytes(self.plan,{},root=self.root)
        self.disk.return_value=required-1
        with self.assertRaisesRegex(ValueError,'Insufficient free disk'):
            self.freeze()
        self.assertFalse(self.directory.exists())
        self.disk.return_value=10**15;plan=self.freeze()
        self.assertEqual(plan['resource_budget']['reserve_bytes'],20*1024**3)
        partial={'gamma-left':{'initial_primaries':2}}
        self.assertLess(C.required_launch_disk_bytes(plan,partial,root=self.root),required)
        self.disk.return_value=required-1;never=Mock(side_effect=AssertionError('disk gate must precede spawn'))
        with self.assertRaisesRegex(ValueError,'Insufficient free disk'):
            C.launch(self.directory,root=self.root,spawn=never)
        never.assert_not_called();self.assertFalse((self.directory/'launcher.json').exists())

    def test_compressed_storage_measurement_preserves_every_pilot_byte(self):
        original={g['id']:C.file_inventory(self.inputs/('pilot-'+g['id'])) for g in self.plan['groups']}
        target=self.root/'.local/storage-measurement'
        evidence=C.measure_storage(self.plan,self.acceptance,target,root=self.root)
        binding=self.binding(target/'measurement.json')
        self.assertEqual(C.verify_storage_measurement(self.plan,self.acceptance,binding,root=self.root),evidence)
        for group in self.plan['groups']:
            self.assertEqual(C.file_inventory(self.inputs/('pilot-'+group['id'])),original[group['id']])
        packed=self.root/next(iter(evidence['groups'][0]['archives'].values()))['archive']['ref']
        packed.write_bytes(packed.read_bytes()+b'tampered')
        with self.assertRaisesRegex(ValueError,'Frozen artifact changed'):
            C.verify_storage_measurement(self.plan,self.acceptance,binding,root=self.root)

    def test_compressed_projection_scales_fixed_metadata_by_chunk_not_primary(self):
        target=self.root/'.local/storage-measurement'
        plan=copy.deepcopy(self.plan);group=plan['groups'][0];group['primary_count']=20001
        group['partition']=C.B.partition(group['primary_count'],group['master_seed'])
        evidence=C.measure_storage(plan,self.acceptance,target,root=self.root)
        groups,temporary=C.storage_projection(plan,C.read(self.root/self.acceptance['ref']),evidence)
        sample=evidence['groups'][0]
        payload=sum(a['archive']['bytes'] for a in sample['archives'].values())+sample['native_store_bytes']+sample['other_variable_bytes']
        fixed=sample['fixed_chunk_bytes']+sample['chunk_seal_allowance_bytes']
        self.assertEqual(groups[group['id']],payload*20001+3*fixed)
        self.assertGreater(temporary,sample['native_store_bytes'])
        self.assertIn('transport/emlow-data.json',sample['fixed_chunk_files'])
        binding=self.binding(target/'measurement.json')
        plan['resource_budget']=C.budget_from_acceptance(plan,self.acceptance,multiplier=2.,storage_measurement=binding,root=self.root)
        totals={g['id']:{'initial_primaries':g['primary_count']} for g in plan['groups']}
        totals[group['id']]['initial_primaries']=20000
        budget=plan['resource_budget']
        self.assertEqual(C.required_launch_disk_bytes(plan,totals,root=self.root),
                         2*(payload+fixed)+budget['max_chunk_temporary_bytes']+budget['reserve_bytes'])

    def test_compressed_budget_keeps_reserve_and_launch_gate_and_binds_measurement(self):
        target=self.root/'.local/storage-measurement';C.measure_storage(self.plan,self.acceptance,target,root=self.root)
        binding=self.binding(target/'measurement.json')
        self.plan['resource_budget']=C.budget_from_acceptance(self.plan,self.acceptance,multiplier=2.,storage_measurement=binding,root=self.root)
        self.assertEqual(self.plan['resource_budget']['reserve_bytes'],20*1024**3)
        needed=C.required_launch_disk_bytes(self.plan,{},root=self.root);self.disk.return_value=needed-1
        with self.assertRaisesRegex(ValueError,'Insufficient free disk'):self.freeze()
        self.disk.return_value=10**15;plan=self.freeze()
        self.assertEqual(plan['resource_budget']['storage_measurement'],binding)
        evidence=C.read(target/'measurement.json');evidence['groups'][0]['fixed_chunk_bytes']=0
        C.write(target/'measurement.json',evidence)
        plan['resource_budget']['storage_measurement']=self.binding(target/'measurement.json')
        with self.assertRaisesRegex(ValueError,'fixed/native byte census changed'):C.verify_resource_budget(plan,self.root)

    def test_low_disk_stops_at_sealed_chunk_and_resumes_without_rerunning_it(self):
        plan=self.freeze();transport=FakeTransport()
        threshold=plan['resource_budget']['max_chunk_temporary_bytes']+plan['resource_budget']['reserve_bytes']
        def factory(*args):return self.factory(*args,after=lambda:setattr(self.disk,'return_value',threshold-1))
        stopped=C.run(self.directory,root=self.root,transport=transport,worker_factory=factory)
        self.assertEqual(stopped['status'],'stopped_low_disk');self.assertEqual(len(transport.calls),1)
        self.assertTrue(self.workers[0].closed);self.assertFalse((self.directory/'COMPLETE.json').exists())
        first=next(C.chunks(plan));done=C.chunk_path(self.directory,first)/'DONE.json';before=C.sha(done)
        self.assertEqual(C.status(self.directory,root=self.root)['disk_free_bytes'],threshold-1)
        self.disk.return_value=10**15
        result=C.run(self.directory,resume=True,root=self.root,transport=transport,worker_factory=self.factory)
        self.assertEqual(result['initial_primaries'],5);self.assertEqual(C.sha(done),before)
        self.assertEqual(len(transport.calls),4)

    def test_stop_resume_skips_done_and_archives_exact_raw_bytes(self):
        plan=self.freeze();transport=FakeTransport()
        def stop_factory(*args):return self.factory(*args,after=lambda:C.stop(self.directory,root=self.root))
        stopped=C.run(self.directory,root=self.root,transport=transport,worker_factory=stop_factory)
        self.assertEqual(stopped['status'],'stopped');self.assertEqual(len(transport.calls),1)
        first=next(C.chunks(plan));folder=C.chunk_path(self.directory,first);before=C.sha(folder/'DONE.json')
        self.assertTrue(self.workers[0].closed);done=C.verify_done(self.directory,plan,first)
        self.assertFalse((folder/'transport/truth.lh5').exists());self.assertFalse((folder/'transport/stream/events.jsonl').exists())
        for ref,record in done['archives'].items():
            C.verify_archive(folder/(ref+'.gz'),record['original_sha256'],record['original_bytes'])
        selected=C.read(folder/'selection.json')
        self.assertEqual(selected['seed'],first['batch']['radiation_seed'])
        completed=C.run(self.directory,resume=True,root=self.root,transport=transport,worker_factory=self.factory)
        self.assertEqual(completed['status'],'completed_with_native_failures')
        self.assertEqual(completed['initial_primaries'],5);self.assertEqual(len(transport.calls),4)
        self.assertEqual(C.sha(folder/'DONE.json'),before);self.assertTrue(all(w.closed for w in self.workers))
        self.assertEqual(completed['groups']['gamma-left']['line_photon_counts'],{'fixture-line':2})
        never=Mock(side_effect=AssertionError('completed science must not restart'))
        self.assertEqual(C.run(self.directory,resume=True,root=self.root,transport=never,worker_factory=never),completed)
        never.assert_not_called()

    def test_changed_done_store_and_source_refuse_new_work(self):
        plan=self.freeze();transport=FakeTransport()
        C.run(self.directory,root=self.root,max_chunks=1,transport=transport,worker_factory=self.factory)
        folder=C.chunk_path(self.directory,next(C.chunks(plan)))
        with (folder/'events.sqlite').open('ab') as output:output.write(b'changed')
        never=Mock(side_effect=AssertionError('must reject before new science'))
        with self.assertRaisesRegex(ValueError,'artifact census/hash'):
            C.run(self.directory,resume=True,root=self.root,transport=never,worker_factory=never)
        never.assert_not_called()
        (self.root/C.SOURCES[0]).write_bytes(b'changed implementation')
        with self.assertRaisesRegex(ValueError,'Frozen source changed'):C.read_plan(self.directory,root=self.root)

    def test_sealed_response_recovers_export_without_restarting_transport_or_native(self):
        plan=self.freeze();transport=FakeTransport()
        with patch.object(C,'seal_chunk',side_effect=RuntimeError('synthetic archive/export interruption')):
            with self.assertRaisesRegex(RuntimeError,'archive/export interruption'):
                C.run(self.directory,root=self.root,transport=transport,worker_factory=self.factory)
        first=next(C.chunks(plan));folder=C.chunk_path(self.directory,first)
        self.assertTrue((folder/'events.sqlite').exists());self.assertFalse((folder/'DONE.json').exists())
        before=C.sha(folder/'events.sqlite');(folder/'response.json').unlink()
        never=Mock(side_effect=AssertionError('sealed science must be reused'))
        result=C.run(self.directory,resume=True,max_chunks=1,root=self.root,transport=never,worker_factory=never)
        self.assertEqual(result['status'],'stopped');never.assert_not_called()
        self.assertEqual(C.sha(folder/'events.sqlite'),before);C.verify_done(self.directory,plan,first)

    def test_error_preserves_partial_attempt_and_complete_is_not_written(self):
        self.freeze()
        class Broken:
            def process(self,folder,selection,tick):
                Path(folder).mkdir(parents=True);(Path(folder)/'unique-failure.txt').write_bytes(b'preserve')
                raise RuntimeError('synthetic concrete failure')
        with self.assertRaisesRegex(RuntimeError,'synthetic concrete failure'):
            C.run(self.directory,root=self.root,transport=Broken(),worker_factory=self.factory)
        self.assertEqual(C.status(self.directory,root=self.root)['status'],'failed')
        self.assertFalse((self.directory/'COMPLETE.json').exists())
        self.assertEqual(next((self.directory/'chunks').rglob('unique-failure.txt')).read_bytes(),b'preserve')
        self.assertFalse((self.directory/'.worker.lock').exists())

    def test_live_unknown_and_dead_pid_reuse_locks_are_distinguished(self):
        self.freeze();lock=self.directory/'.worker.lock';lock.mkdir()
        old={'pid':777,'process_start_identity':'old-start','token':'old'};C.write(lock/'owner.json',old)
        for observed in ('old-start','unknown'):
            with self.assertRaisesRegex(ValueError,'live or.*unknown'):
                with C.locked(self.directory,resume=True,reader=lambda pid:observed):pass
        with self.assertRaisesRegex(ValueError,'explicit resume'):
            with C.locked(self.directory,reader=lambda pid:None):pass
        def reused(pid):return 'new-reused-start' if pid==777 else 'current-start'
        with C.locked(self.directory,resume=True,reader=reused) as owner:self.assertEqual(owner['process_start_identity'],'current-start')
        self.assertFalse(lock.exists());self.assertEqual(C.read(self.directory/'recovered-lock.json')['prior_owner'],old)

    def test_owned_lock_cleanup_retries_and_retains_owner_if_removal_fails(self):
        self.freeze();path=self.directory/'.worker.lock';path.mkdir()
        owner={'pid':123,'process_start_identity':'dead','token':'owned'};C.write(path/'owner.json',owner)
        if os.name=='nt':path.chmod(C.stat.S_IREAD)
        original=Path.rmdir;calls=[]
        def transient(p):
            if p==path:
                calls.append(1)
                if len(calls)==1:raise PermissionError('temporary owned directory denial')
            return original(p)
        with patch.object(Path,'rmdir',transient),patch.object(C.time,'sleep'):
            C.release_owned_lock(path,owner)
        self.assertEqual(len(calls),2);self.assertFalse(path.exists())
        path.mkdir();C.write(path/'owner.json',owner)
        with patch.object(Path,'rmdir',side_effect=PermissionError('persistent denial')),patch.object(C.time,'sleep'):
            with self.assertRaisesRegex(PermissionError,'persistent denial'):C.release_owned_lock(path,owner,attempts=2)
        self.assertEqual(C.read(path/'owner.json'),owner)
        self.assertEqual(C.read(self.directory/'.worker.lock.cleanup-failure.json')['owner'],owner)

    def test_anonymous_empty_lock_is_never_adopted(self):
        self.freeze();path=self.directory/'.worker.lock';path.mkdir()
        with self.assertRaisesRegex(ValueError,'Unrecognized campaign lock'):
            with C.locked(self.directory,resume=True,reader=lambda pid:None):pass
        self.assertEqual(list(path.iterdir()),[])

    def test_orphan_child_identity_blocks_resume_and_unknown_launch_is_preserved(self):
        plan=self.freeze();first=next(C.chunks(plan));folder=C.chunk_path(self.directory,first);folder.mkdir(parents=True)
        C.progress(self.directory,plan,'running_transport',{},first)
        record=folder/'active-transport.json'
        C.write(record,{'status':'running','pid':777,'process_start_identity':'child-start'})
        for observed in ('child-start','unknown'):
            with self.assertRaisesRegex(ValueError,'prior native/transport child'):
                C.inactive_children(self.directory,reader=lambda pid:observed)
        C.inactive_children(self.directory,reader=lambda pid:None)
        C.write(record,{'status':'launching'})
        with self.assertRaisesRegex(ValueError,'interrupted child launch'):
            C.inactive_children(self.directory,reader=lambda pid:None)
        self.assertEqual(C.read(record),{'status':'launching'})

    def test_rehashed_fresh_field_request_is_not_admitted(self):
        request_path=self.root/self.plan['native_request']['ref'];request=C.read(request_path)
        request['numerics']['field_policy']='fresh';C.write(request_path,request)
        self.plan['native_request']=self.binding(request_path)
        accepted=C.read(self.root/self.acceptance['ref']);accepted['physics_sha256']=C.physics_sha256(self.plan)
        C.write(self.root/self.acceptance['ref'],accepted)
        with self.assertRaisesRegex(ValueError,'fresh native field solve'):
            C.freeze(self.directory,self.plan,self.binding(self.root/self.acceptance['ref']),root=self.root)
        self.assertFalse(self.directory.exists())

    def test_detached_launch_is_hidden_idempotent_and_status_does_not_hash_science(self):
        self.freeze();spawn=Mock(return_value=Mock(pid=9876));reader=lambda pid:'start-'+str(pid)
        result=C.launch(self.directory,root=self.root,spawn=spawn,reader=reader)
        self.assertEqual(result['status'],'launched');self.assertEqual(spawn.call_count,1)
        args,kwargs=spawn.call_args
        self.assertIn('run',args[0]);self.assertFalse(kwargs['shell']);self.assertEqual(kwargs['stdin'],C.subprocess.DEVNULL)
        if os.name=='nt':self.assertTrue(kwargs['creationflags']&C.subprocess.CREATE_NO_WINDOW)
        else:self.assertTrue(kwargs['start_new_session'])
        self.assertEqual(C.launch(self.directory,root=self.root,spawn=spawn,reader=reader)['status'],'already_running')
        self.assertEqual(spawn.call_count,1)
        with patch.object(C,'sha',side_effect=AssertionError('monitor must stay compact')):
            value=C.status(self.directory,root=self.root,reader=reader)
        self.assertEqual(value['status'],'prepared')

    def test_uncertain_detached_launch_is_preserved_and_cannot_spawn_twice(self):
        self.freeze()
        with self.assertRaisesRegex(OSError,'synthetic interrupted spawn'):
            C.launch(self.directory,root=self.root,spawn=Mock(side_effect=OSError('synthetic interrupted spawn')))
        self.assertEqual(C.read(self.directory/'launcher.json')['status'],'launching')
        never=Mock(side_effect=AssertionError('uncertain launch must not spawn again'))
        with self.assertRaisesRegex(ValueError,'interrupted detached launch'):
            C.launch(self.directory,resume=True,root=self.root,spawn=never)
        never.assert_not_called()

    def test_runtime_nuclear_data_and_emlow_drift_refuse_radiation_before_dispatch(self):
        plan=self.freeze();context=plan['transport_context'];first=next(C.chunks(plan))
        folder=C.chunk_path(self.directory,first);folder.mkdir(parents=True)
        selected=C.selection_for(plan,first)
        C.write(folder/'selection.json',selected)
        checked={'selection':selected,'runtime':{'changed_runtime':True},'decay_data':None}
        C.write(folder/'source-checked.json',checked)
        transport=C.Transport(self.root,context)
        with patch.object(transport,'command') as commands:
            with self.assertRaisesRegex(ValueError,'runtime or nuclear data'):
                transport.process(folder,selected,lambda:None)
            checked['runtime']=context['runtime'];checked['decay_data']={'unexpected_nuclear_data':True}
            C.write(folder/'source-checked.json',checked)
            with self.assertRaisesRegex(ValueError,'runtime or nuclear data'):
                transport.process(folder,selected,lambda:None)
            checked['decay_data']=None;C.write(folder/'source-checked.json',checked)
            target=folder/'transport';target.mkdir();C.write(target/'prepared.json',{})
            C.write(target/'emlow-data.json',{'changed_emlow':True})
            with self.assertRaisesRegex(ValueError,'EMLOW bytes'):
                transport.process(folder,selected,lambda:None)
            commands.assert_not_called()
        self.assertEqual(C.emlow_digest({'hash_wall_s':1.,'bytes':'same'}),
                         C.emlow_digest({'hash_wall_s':99.,'bytes':'same'}))

    def test_uncertain_existing_transport_is_never_restarted(self):
        folder=self.root/'.local/uncertain';target=folder/'transport';target.mkdir(parents=True)
        selected={'name':'synthetic'};C.write(folder/'selection.json',selected);C.write(folder/'source-checked.json',{'selection':selected})
        C.write(target/'prepared.json',{});(target/'truth.lh5').write_bytes(b'unique incomplete raw evidence')
        transport=C.Transport(self.root)
        with patch.object(transport,'command') as commands,self.assertRaisesRegex(ValueError,'Uncertain radiation'):
            transport.process(folder,selected,lambda:None)
        commands.assert_not_called();self.assertEqual((target/'truth.lh5').read_bytes(),b'unique incomplete raw evidence')


if __name__=='__main__':unittest.main(verbosity=2)
