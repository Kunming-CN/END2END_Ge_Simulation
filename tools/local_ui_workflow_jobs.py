"""Persistent owned GUI dispatch for the shared finite scenario workflow."""
from __future__ import annotations
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import sys
import threading

import scenario_workflow as W
import workflow_inspection as I
import workflow_recovery as R
import workflow_finalize as F
import saved_waveforms
import saved_focus_waveforms
from saved_terminal import Verifier
from local_ui_jobs import ControlError, process_identity, safe_path

STATE='.local/local-control-v1'
ACTIVE=('dispatch_uncertain','running','stop_requested')


class WorkflowController:
    def __init__(self,root=None,*,coordination_lock=None,peer_busy=None,resolver=None,launcher=None):
        self.root=Path(root or W.ROOT);self._lock=coordination_lock or threading.RLock()
        self._peer_busy=peer_busy or (lambda:False);self._resolver=resolver or W.check
        self._launcher=launcher or self._spawn;self._checks={};self._active=None;self._entry_thread=None
        self._saved_verifier=Verifier(self.root)
        path=safe_path(self.root,STATE+'/workflow-jobs.json')
        self._state_path=path
        if path.exists():
            saved=W.read(path);W.require(saved.get('kind')=='local_workflow_jobs_v1' and type(saved.get('jobs')) is list,'Saved workflow control state is unsupported.')
            self._jobs=saved['jobs']
            seen=set()
            for job in self._jobs:
                W.require(type(job) is dict and re.fullmatch('[0-9a-f]{32}',str(job.get('id',''))) and
                          job.get('status') in (*ACTIVE,*W.TERMINAL,'stopped','inspected_failure','verified_transport') and
                          job['id'] not in seen and type(job.get('created_utc')) is str and
                          job.get('mode') in ('run','resume','continue') and type(job.get('plan')) is dict and
                          job.get('name')==job['plan'].get('resolved',{}).get('selection',{}).get('name'),
                          'Invalid saved workflow job; preserve it for inspection.')
                seen.add(job['id'])
                W.run_path(job['name'],self.root)
                driver=job.get('driver')
                W.require(driver is None or (type(driver) is dict and set(driver)=={'pid','identity'} and
                          type(driver['pid']) is int and driver['pid']>0 and
                          (driver['identity'] is None or type(driver['identity']) is str)),
                          'Invalid saved workflow process identity.')
                if job['status'] in ACTIVE:
                    job['status']='dispatch_uncertain'
                    job['error']='A prior driver may have nested workers. Inspect existing receipts; no replacement will be launched.'
        else:self._jobs=[]

    def set_peer_busy(self,probe):self._peer_busy=probe

    def own_busy(self):
        with self._lock:
            return (self._active is not None or any(j['status'] in ACTIVE or not W.identity_ended(j.get('driver')) for j in self._jobs) or
                    (self._entry_thread!=threading.get_ident() and W.lease_busy(self.root)))

    @contextmanager
    def scientific_entry(self):
        """Retained legacy routes reserve under the same CLI exclusion."""
        with self._lock:
            W.require(not self.own_busy(),'A workflow or uncertain dispatch is active.')
            with W.execution_lease(self.root):
                self._entry_thread=threading.get_ident()
                try:
                    W.verify_dispatch_reservations(None,self.root)
                    yield
                finally:self._entry_thread=None

    def _idle(self):
        W.require(not self.own_busy() and not self._peer_busy(),'Another calculation or uncertain dispatch is active.')

    def _persist(self):
        W.write(self._state_path,{'kind':'local_workflow_jobs_v1','jobs':self._jobs})

    def setup(self):
        checks=[]
        for label,relative in (('Pinned cryostat inventory','transport/cryostat-source.json'),
                               ('Julia project','simulation/Manifest.toml')):
            checks.append({'label':label,'available':safe_path(self.root,relative).is_file()})
        try:
            sys.path.insert(0,str(W.ROOT/'transport')) if str(W.ROOT/'transport') not in sys.path else None
            from scenario_source_portable import file_readiness
            portable=file_readiness(self.root)
            checks.append({'label':'Portable source exporter and matching build receipt','available':True})
        except (OSError,ValueError,KeyError,ControlError):
            portable=None;checks.append({'label':'Portable source exporter and matching build receipt','available':False})
        try:
            runtime=W.runtime_identity(2)
            checks.append({'label':'Existing pinned Julia executable','available':True})
        except (OSError,ControlError):
            runtime=None;checks.append({'label':'Existing pinned Julia executable','available':False})
        try:W.source_pins('AK02',self.root,portable=True);checks.append({'label':'Exact model and upstream input bytes','available':True})
        except (OSError,ValueError,KeyError,ControlError):checks.append({'label':'Exact model and upstream input bytes','available':False})
        return {'status':'file_readiness_only','checks':checks,'runtime_identity':runtime,'portable_source':portable,
                'ready_for_config_check':all(c['available'] for c in checks),'science_calls':0,
                'note':'File readiness only. Run.cmd setup -BuildPortableSourceExporter explicitly builds the exporter in the existing locked environment. Check verifies current build/runtime identities; opening Control installs or builds nothing.',
                'guide':W.catalog(self.root)['setup_guide']}

    def check(self,config):
        with self._lock:
            self._idle();plan=self._resolver(config,root=self.root)
            check_id=secrets.token_hex(32);self._checks[check_id]=copy.deepcopy(plan)
            return dict(plan,check_id=check_id)

    def start(self,check_id):
        with self._lock:
            self._idle();W.require(type(check_id) is str and check_id in self._checks,'Check this configuration before Start.')
            plan=self._checks[check_id]
            # Reconstruct the complete trusted plan; rehashed browser edits are not authority.
            actual=self._resolver(plan['resolved']['selection'],root=self.root)
            W.require(W.encoded(actual)==W.encoded(plan),'Inputs, settings or runtime changed after Check.')
            name=plan['resolved']['selection']['name']
            W.require(not any(j['name'].casefold()==name.casefold() for j in self._jobs),'This run name is already recorded.')
            job={'id':secrets.token_hex(16),'name':name,'status':'dispatch_uncertain','plan':plan,
                 'created_utc':W.utc(),'driver':None,'mode':'run'}
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(plan,self.root)
                self._jobs.append(job);self._persist();self._checks.pop(check_id)
            return self._launch(job)

    def _launch(self,job):
        self._active=job['id'];thread=threading.Thread(target=self._work,args=(job,),daemon=True,name='workflow-'+job['id'])
        thread.start();return self._view(job)

    def _spawn(self,argv,log,on_spawn):
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        with log.open('xb') as stream:
            p=subprocess.Popen(argv,cwd=self.root,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                               shell=False,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            on_spawn(p.pid,process_identity(p.pid));return p.wait()

    def _work(self,job):
        try:
            plan_path=safe_path(self.root,STATE+'/workflow-plans/'+job['id']+'.json')
            if job['mode'] in ('run','continue'):W.write(plan_path,job['plan'],fresh=True)
            log=safe_path(self.root,STATE+'/workflow-logs/'+job['id']+'.log');log.parent.mkdir(parents=True,exist_ok=True)
            argv=[sys.executable,'-B',str(self.root/'tools/scenario_workflow.py'),job['mode']]
            if Path(sys.executable).name.casefold()=='pvpython.exe':argv[1:1]=['--no-mpi','--disable-registry']
            argv+=['--plan',str(plan_path)] if job['mode'] in ('run','continue') else ['--name',job['name']]
            argv+=['--dispatch-id',job['id']]
            def spawned(pid,identity):
                with self._lock:
                    job.update(driver={'pid':pid,'identity':identity},status='running');self._persist()
            code=self._launcher(argv,log,spawned)
            with self._lock:
                directory=W.run_path(job['name'],self.root)
                receipt=W.read(directory/'run.json') if (directory/'run.json').exists() else None
                if code==0 and receipt and receipt['status'] in (*W.TERMINAL,'stopped'):
                    if receipt['status'] in W.TERMINAL:W.inspect(job['name'],self.root)
                    job['status']=receipt['status'];job.pop('error',None)
                else:
                    job.update(status='dispatch_uncertain',error='The workflow did not return verified terminal or stopped stages. Retain output and inspect possible nested workers.')
                    I.capture(job,self.root)
                self._persist()
        except BaseException as error:
            with self._lock:job.update(status='dispatch_uncertain',error=str(error));self._persist()
        finally:
            with self._lock:self._active=None

    def stop(self,name):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None);W.require(job is not None,'Unknown owned run.')
            W.require(job['status'] in ('running','stop_requested'),'The run has no active committed stage yet.')
            directory=W.run_path(name,self.root);path=directory/'STOP.json'
            W.require((directory/'run.json').is_file() and W.read(directory/'run.json')['status']=='running',
                      'Wait for the first committed run receipt before requesting Stop.')
            if not path.exists():W.write(path,{'requested_utc':W.utc()},fresh=True)
            job['status']='stop_requested';self._persist();return self._view(job)

    def resume(self,name):
        with self._lock:
            self._idle();job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and job['status']=='stopped','Only this interface\'s stage-boundary stopped runs can resume.')
            W.admit(job['plan'],self.root,resume=True)
            # New dispatch/log identity; selected settings are the preserved plan.
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(job['plan'],self.root)
                job.update(id=secrets.token_hex(16),status='dispatch_uncertain',driver=None,mode='resume')
                self._persist()
            return self._launch(job)

    def verify(self,name):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None);W.require(job is not None,'Unknown owned run.')
            receipt=W.inspect(name,self.root)
            W.require(receipt['configuration_sha256']==job['plan']['configuration_sha256'],'Saved run differs from owned plan.')
            W.require(receipt['status'] in W.TERMINAL,'Run has no verified completion; incomplete evidence is retained.')
            driver=job.get('driver')
            W.require(W.identity_ended(driver),'Owned driver is active or its lifetime is unknown.')
            job.update(status=receipt['status']);job.pop('error',None);self._persist();return self._view(job)

    def inspect_failure(self,name):
        with self._lock:
            W.require(self._active is None and not W.lease_busy(self.root),'Wait for active work before inspecting a failed launch.')
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and job['status']=='dispatch_uncertain','Only an uncertain owned failed launch can be inspected.')
            with W.execution_lease(self.root):
                stamp=I.inspect_failure(job,self.root)
                job.update(status='inspected_failure',inspection_sha256=stamp);job.pop('error',None);self._persist()
            return self._view(job)

    def finalize_results(self,name):
        with self._lock:
            W.require(self._active is None and not W.lease_busy(self.root) and not self._peer_busy(),
                      'Wait for active work or verify existing saved work before finalizing results.')
            W.require(any(j['name']==name and j['status']=='dispatch_uncertain' for j in self._jobs),'Unknown owned terminal-response failure.')
            # The same closed saved-data policy serves GUI and CLI. It settles
            # durable state only after a complete W.inspect; no child launches.
            F.finalize(name,self.root)
            self._jobs=W.read(self._state_path)['jobs']
            return self._view(next(j for j in self._jobs if j['name']==name))

    def continue_prefix(self,name,new_name):
        with self._lock:
            parent=next((j for j in self._jobs if j['name']==name),None)
            W.require(R.eligible_name(name) and parent and parent['status']=='dispatch_uncertain',
                      'Only a recognized sealed pre-response interruption can continue from transport.')
            W.require(self._active is None and not W.lease_busy(self.root) and not self._peer_busy() and
                      all(j is parent or (j['status'] not in ACTIVE and W.identity_ended(j.get('driver'))) for j in self._jobs),
                      'Other active, unknown or uncertain work prevents continuation.')
            W.require(not any(j['name'].casefold()==new_name.casefold() for j in self._jobs),'Choose a new unused output name.')
            with W.execution_lease(self.root):
                inspection=R.inspect_parent(parent,self.root)
                config=copy.deepcopy(parent['plan']['resolved']['selection']);config['name']=new_name
                plan=self._resolver(config,root=self.root);R.compatible(parent['plan']['resolved'],plan['resolved'])
                # One durable publication retires only the inspected old dispatch and
                # reserves the new derivative while the common lease is still held.
                stamp=R.release(parent,plan,inspection,self.root)
                job={'id':secrets.token_hex(16),'name':new_name,'status':'dispatch_uncertain','plan':plan,
                     'created_utc':W.utc(),'driver':None,'mode':'continue','transport_parent':name}
                parent.update(status='verified_transport',prefix_authority_sha256=stamp);parent.pop('error',None)
                self._jobs.append(job);self._persist()
            return self._launch(job)

    def _view(self,job):
        out={k:copy.deepcopy(job[k]) for k in ('id','name','status','created_utc')}
        out['selection']=copy.deepcopy(job['plan']['resolved']['selection'])
        out['configuration_sha256']=job['plan']['configuration_sha256']
        out['output']=W.BASE+'/'+job['name'];out['error']=job.get('error');out['stages']={}
        out['can_continue_prefix']=R.eligible_name(job['name']) and job['status']=='dispatch_uncertain'
        out['can_finalize_results']=False
        directory=W.run_path(job['name'],self.root)
        try:
            receipt=W.read(directory/'run.json');out['stages']=receipt['stages'];out['counts']=receipt.get('counts')
            out['can_finalize_results']=job['status']=='dispatch_uncertain' and F.candidate(directory)
            # This live progress is display-only until terminal artifact verification.
            if (directory/'response/progress.json').exists():out['response_progress']=W.read(directory/'response/progress.json')
        except (OSError,ValueError,ControlError):pass
        return out

    def snapshot(self):
        with self._lock:return {'kind':'local_workflow_state_v1','busy':self.own_busy(),'jobs':[self._view(j) for j in self._jobs]}

    def artifact(self,name,file):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None);W.require(job,'Unknown owned run.')
            directory=W.run_path(name,self.root)
            if file.endswith('.log') and file in {stage+'.log' for stage in W.STAGES}:
                path=safe_path(directory,file)
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-256*1024));body=stream.read(256*1024)
                return body,'text/plain; charset=utf-8'
            W.require(job['status'] in W.TERMINAL,'Verify completed results before downloading.')
            self._saved_verifier.inspect(name)
            complete=W.read(directory/'COMPLETE.json');W.require(file in complete['artifacts'] or file=='COMPLETE.json','Unsupported result artifact.')
            path=safe_path(directory,file);W.require(path.stat().st_size<=64*1024*1024,'Artifact exceeds the browser size limit.')
            mime='text/html; charset=utf-8' if file.endswith('.html') else 'text/plain; charset=utf-8' if file.endswith(('.csv','.jsonl')) else 'application/json; charset=utf-8'
            return path.read_bytes(),mime

    def waveforms(self,name,primary_id,group_id):
        with self._lock:
            body,mime=self.artifact(name,'response/summary.html')
            job=next(j for j in self._jobs if j['name']==name)
            return saved_waveforms.project(body,name,job['plan']['configuration_sha256'],primary_id,group_id)

    def focused_waveforms(self,name,primary_id,group_id):
        with self._lock:
            self.artifact(name,'response/summary.html')
            job=next(j for j in self._jobs if j['name']==name)
            reply=saved_focus_waveforms.project(W.run_path(name,self.root),name,job['plan']['configuration_sha256'],primary_id,group_id,self.root)
            self._saved_verifier.inspect(name)
            return reply
