import copy
from contextlib import closing, redirect_stdout
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import gegi_boundary_failure_recovery as B
from test_gegi_native_signal_only import native_payload


class BoundaryRecoveryTests(unittest.TestCase):
    def setUp(self):
        temporary=tempfile.TemporaryDirectory(prefix='boundary-recovery-',dir=B.ROOT/'.local')
        self.addCleanup(temporary.cleanup);self.root=Path(temporary.name);self.out=self.root/'phase';self.out.mkdir()
        self.source=self.root/'source';self.source.mkdir();(self.source/'compton-candidates.sqlite').write_bytes(b'unchanged input fixture')
        field=self.root/'field.bin';field.write_bytes(b'unchanged field fixture')
        self.request={'numerics':{'drift_dt_ns':1.,'drift_cap_ns':1000.},'source_sha256':{},'model_sha256':'a'*64,
            'field_cache':{'ref':str(field.relative_to(B.ROOT)),'sha256':B.response.file_sha(field)}}
        B.response.write(self.out/'native-request.json',self.request);(self.out/'producer-source.zip').write_bytes(b'frozen source fixture')
        self.inputs=[];self.rows={}
        for ordinal,(eid,status,support) in enumerate(((27,'native_failed',1001.),(28,'native_failed',1001.),
                (29,'native_failed',1001.),(30,'completed',1001.),(31,'step_limit',5001.)),1):
            onset=1e6+ordinal*11000
            group={'event_id':eid,'group_id':0,'group_origin_time_ns':onset,
                'steps':[{'raw_row_index':ordinal,'time_ns':onset,'energy_keV':4.}]}
            self.inputs.append((ordinal,group,{'status':status}))
            self.rows[eid,0]={'ordinal':ordinal,'event_id':eid,'group_id':0,'input_sha256':B.store.sha(B.store.encoded(group)),
                'new_status':status,'new_domain_error':'Native floating-boundary projection failed' if status=='native_failed' else None,
                'complete':status=='completed','native_support_ns':support,'native_origin':'original_cap_layer',
                'native_record_binding':{'producer':'kept'},'timing_status':'measured','elapsed_seconds':2.}
        self.acquisition={'live_time_ns':5e6,'excluded_intervals_ns':self.mask([27,28,29,31])}
        B.response.write(self.source/'candidate-acquisition.json',self.acquisition)
        self.previous={'conditional_history':{'old_unavailable_union':{'excluded_time_ns':100.},
            'remaining_unknown_union':{'fixture':True},'remaining_intervals_ns':self.mask([27,28,29,31])}}
        self.old_identity={'source_ref':str(self.source.relative_to(B.ROOT)),
            'source_sha256':B.response.file_sha(self.source/'compton-candidates.sqlite'),'group_count':5}
        self.identity={'kind':B.KIND,**self.old_identity,'baseline':{'ref':str(self.root.relative_to(B.ROOT))},
            'selected_ordinals':[1,2,3],'selected_groups':3,'original_groups':5,'inherited_acceptance':{},
            'request_sha256':B.response.file_sha(self.out/'native-request.json'),'producer_sha256':B.response.file_sha(B.__file__)}
        B.response.write(self.out/'identity.json',self.identity);self.calls=[]

    def mask(self,ids):
        history=B.R.MissingHistory(5e6,native_support_ns=1001.)
        for _,group,_ in self.inputs:
            if group['event_id'] in ids:
                history.native_support_ns=5001. if group['event_id']==31 else 1001.
                history.add(group['group_origin_time_ns'],group['steps'][0]['time_ns'],4.)
        return history.intervals()

    def payload(self,group,status):
        event,signals=native_payload();event.update(event_id=group['event_id'],group_id=0,input_group=group,input_steps=group['steps'],status=status)
        event['steps'][0]['endpoints']=[{'status':'contact','step_limit_reached':False,'contact_ids':[3]},
            {'status':'contact','step_limit_reached':False,'contact_ids':[24]}]
        if status=='step_limit':event['steps'][0]['endpoints'][0].update(status=status,step_limit_reached=True,contact_ids=[])
        return event,signals

    def baseline(self,*args):return self.identity['baseline'],self.old_identity,self.request,self.previous,self.rows

    def worker(self,request,spool):
        def process(group,native):
            self.calls.append(group['event_id']);event,signals=self.payload(group,'completed' if group['event_id']==27 else 'step_limit')
            native.append(group['event_id'],0,event,signals,B.store.sha(B.store.encoded(group)))
            return native.read(group['event_id'],0)[0]
        ready={'drift_dt_ns':1.,'drift_numerics':{'max_steps':1001},'field_cache_sha256':self.request['field_cache']['sha256'],
            'model_sha256':self.request['model_sha256']}
        return SimpleNamespace(process=SimpleNamespace(pid=os.getpid()),start=lambda:ready,close=lambda:None,process_group=process)

    def test_stop_resume_reuses_committed_rows_and_keeps_mixed_support(self):
        with patch.object(B,'baseline',side_effect=self.baseline),patch.object(B.R,'groups',side_effect=lambda _:iter(self.inputs)),\
                patch.object(B.response,'ResidentWorker',side_effect=self.worker),redirect_stdout(io.StringIO()):
            stopped=B.run(self.out,stop_after_new=1)
            self.assertEqual(stopped['status'],'stopped');self.assertEqual(self.calls,[27])
            # Simulate commit-before-ledger interruption: the next resume must
            # retain the successful row even when its timing append is absent.
            (self.out/'recovery-ledger.jsonl').write_bytes(b'')
            final=B.run(self.out);self.assertEqual(B.run(self.out),final)
        self.assertEqual(self.calls,[27,28,29])
        self.assertEqual(final['conditional_history']['effective_counts'],{'completed':2,'step_limit':3})
        self.assertEqual(final['conditional_history']['remaining_intervals_ns'],self.mask([28,29,31]))
        rows=[json.loads(line) for line in (self.out/'recovery-status.jsonl').read_bytes().splitlines()]
        first=next(row for row in rows if row['event_id']==27)
        self.assertIsNone(first['elapsed_seconds']);self.assertEqual(first['timing_status'],'no_retained_timing_entry')
        retained=next(row for row in rows if row['event_id']==31)
        self.assertEqual(retained,self.rows[31,0]);self.assertEqual(retained['native_support_ns'],5001.)
        with closing(B.store.Store(self.out/'native.sqlite',self.identity)) as native:
            self.assertEqual(set(native.keys()),{(27,0),(28,0),(29,0)})

    def test_selected_class_excludes_limits_and_rejects_unclassified_failure(self):
        self.assertEqual(B.selected_rows(self.rows),{1,2,3})
        altered=copy.deepcopy(self.rows);altered[28,0]['new_domain_error']='different failure'
        with self.assertRaisesRegex(ValueError,'concrete retained'):B.selected_rows(altered)

    def test_acceptance_inheritance_preserves_all_signed_arrays_and_producer(self):
        ordinal,group,_=self.inputs[0];event,signals=self.payload(group,'completed')
        eventpath=self.root/'accepted.json';B.response.write(eventpath,event)
        csv=self.root/'accepted.csv'
        with csv.open('w',encoding='utf-8',newline='') as stream:
            stream.write('contact_id,time_ns,signed_induced_keV,wired_induced_keV\n')
            for cid,values in signals.items():
                for time,q in zip(values['time_ns'],values['signed_induced_keV']):
                    stream.write(f'{cid},{time},{q},{q*(1 if cid<=17 else -1)}\n')
        binding={'event_ref':str(eventpath.relative_to(B.ROOT)),'event_sha256':B.response.file_sha(eventpath),
            'signals_ref':str(csv.relative_to(B.ROOT)),'signals_sha256':B.response.file_sha(csv),'producer_archive_sha256':'b'*64}
        # Diagnostic labels differ from original chronological ordinals. Join
        # accepted data by exact event/group input identity, retaining ordinal 1.
        event['signals_ref']=csv.name;B.response.write(eventpath,event);binding['event_sha256']=B.response.file_sha(eventpath)
        B.response.write(self.root/'request-1000.json',self.request)
        (self.root/'producer-source.zip').write_bytes(b'accepted source fixture')
        B.response.write(self.root/'results.json',{'results':[{'ordinal':'witness-27','event_ref':str(eventpath),
            'drift_cap_ns':1000.,'status':'completed','signals_sha256':binding['signals_sha256']}]})
        accepted_binding={'request_1000_sha256':B.response.file_sha(self.root/'request-1000.json'),
            'producer_archive_sha256':B.response.file_sha(self.root/'producer-source.zip'),'source_file_sha256':{}}
        B.response.write(self.root/'binding.json',accepted_binding)
        B.response.write(self.root/'active-worker.json',{'status':'completed'})
        B.response.write(self.root/'validation.json',{'worker_exit_code':0,'source_hashes_unchanged':True,'exact_success_controls':20,
            **accepted_binding,'results_sha256':B.response.file_sha(self.root/'results.json')})
        with patch.object(B,'baseline',side_effect=self.baseline):prepared=B.prepare(self.root,self.root,self.root/'prepared')
        self.assertEqual(set(prepared['inherited_acceptance']),{'1'})
        self.identity['inherited_acceptance']={'1':binding}
        with closing(B.store.Store(self.out/'inherit.sqlite',self.identity,create=True)) as native:
            B.inherit(ordinal,group,self.identity,native);saved,actual=native.read(27,0,with_signals=True)
            self.assertEqual(actual,signals);self.assertEqual(saved['native_recovery_inherited']['producer_archive_sha256'],'b'*64)
            self.assertEqual(saved['input_group'],group)
        event['input_group']['steps'][0]['energy_keV']=9.;B.response.write(eventpath,event)
        with closing(B.store.Store(self.out/'reject.sqlite',self.identity,create=True)) as native:
            with self.assertRaisesRegex(ValueError,'inherited result changed'):B.inherit(ordinal,group,self.identity,native)


if __name__=='__main__':unittest.main()
