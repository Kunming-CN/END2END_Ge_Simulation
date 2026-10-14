"""Persistent owned GUI dispatch for the shared finite scenario workflow."""
from __future__ import annotations
import copy
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import secrets
import re
import subprocess
import sys
import threading

import scenario_workflow as W
import batch_execution as B
import workflow_inspection as I
import workflow_recovery as R
import workflow_finalize as F
import workflow_launch as L
import saved_waveforms
import saved_focus_waveforms
from saved_terminal import Verifier
from local_ui_jobs import ControlError, process_identity, safe_path

STATE='.local/local-control-v1'
ACTIVE=('dispatch_uncertain','running','stop_requested')
CATALOG_KIND='local_catalog_workflow_v1'

def catalog_backend():
    import catalog_workflow
    return catalog_workflow


def psd_backend():
    import psd_features
    return psd_features


def acquisition_backend():
    import waveform_acquisition
    return waveform_acquisition


class WorkflowController:
    def __init__(self,root=None,*,coordination_lock=None,peer_busy=None,resolver=None,catalog_resolver=None,batch_resolver=None,launcher=None):
        self.root=Path(root or W.ROOT);self._lock=coordination_lock or threading.RLock()
        self._peer_busy=peer_busy or (lambda:False);self._resolver=resolver or W.check
        self._catalog_resolver=catalog_resolver
        self._batch_resolver=batch_resolver or B.check
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
                          job.get('status') in (*ACTIVE,*W.TERMINAL,'stopped','inspected_failure','verified_transport','launch_failed') and
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
                    if not job.get('launch_failure_sha256'):
                        job['error']='A prior driver may have nested workers. Inspect existing receipts; no replacement will be launched.'
        else:self._jobs=[]

    def set_peer_busy(self,probe):self._peer_busy=probe

    def own_busy(self):
        with self._lock:
            return (self._active is not None or any(j['status'] in ACTIVE or not W.identity_ended(j.get('driver')) or
                    not self._valid_retirement(j) for j in self._jobs) or
                    (self._entry_thread!=threading.get_ident() and W.lease_busy(self.root)))

    def _valid_retirement(self,job):
        if job['status']!='launch_failed' and not job.get('launch_recovery_sha256'):return True
        try:L.verify_retirement(job,self.root);return True
        except (OSError,ValueError,KeyError,TypeError,ControlError):return False

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
        ready_for_config_check=all(c['available'] for c in checks)
        backend=catalog_backend()
        catalog_ready=safe_path(self.root,backend.EXPORTER_REF).is_file() and safe_path(self.root,backend.BUILD_REF).is_file()
        checks.append({'label':'Common model geometry exporter and build receipt','available':catalog_ready})
        angle_ready=all(safe_path(self.root,ref).is_file() for ref in
            ('.local/m2a/angle-source-build-v1/cryostat_angle_export','.local/m2a/angle-source-build-v1/exporter-build.json'))
        checks.append({'label':'Angular source geometry exporter and build receipt','available':angle_ready})
        return {'status':'file_readiness_only','checks':checks,'runtime_identity':runtime,'portable_source':portable,
                'catalog_models_file_ready':catalog_ready,
                'angular_source_file_ready':angle_ready,
                'ready_for_config_check':ready_for_config_check,'science_calls':0,
                'note':'File readiness only. Run.cmd setup -BuildPortableSourceExporter builds the original exporter; Run.cmd setup -BuildCatalogSourceExporter builds the common model exporter; Run.cmd setup -BuildAngleSourceExporter builds angular geometry support. These use the existing locked environment. '+('Angular execution is available after a successful Check plan. ' if B.ANGULAR_EXECUTION_READY else 'Nonzero-angle execution is pending end-to-end acceptance. ')+'Check verifies current build/runtime identities; opening Control installs or builds nothing.',
                'guide':W.catalog(self.root)['setup_guide']}

    def check(self,config):
        with self._lock:
            self._idle();plan=self._resolver(config,root=self.root)
            check_id=secrets.token_hex(32);self._checks[check_id]=copy.deepcopy(plan)
            return dict(plan,check_id=check_id)

    def preview_batches(self,request):
        # Preview creates no check_id, reservation, execution lease or output.
        # A future M15b dispatcher needs its own reviewed admission contract.
        with self._lock:
            return W.preview(W.preview_request(request),root=self.root)

    def check_catalog(self,config):
        with self._lock:
            self._idle();resolver=self._catalog_resolver or catalog_backend().check
            plan=resolver(config,root=self.root)
            W.require(plan.get('kind')==CATALOG_KIND and plan.get('status')=='checked_configuration',
                      'A checked shared-model configuration is required.')
            check_id=secrets.token_hex(32);self._checks[check_id]=copy.deepcopy(plan)
            return dict(plan,check_id=check_id)

    @staticmethod
    def _catalog_job(job):return job['plan'].get('kind')==CATALOG_KIND

    def check_batches(self,request):
        with self._lock:
            self._idle();plan=self._batch_resolver(W.preview_request(request),root=self.root)
            if (plan.get('kind')==B.CHECKED_KIND and plan.get('schema_version')==3 and
                plan.get('execution_enabled') is False and B.selection_angle(plan.get('resolved',{}).get('selection',{}))!=0):
                return plan  # No Start token, reservation or computation for an unaccepted pose.
            W.require(plan.get('kind')==B.CHECKED_KIND and plan.get('schema_version')==3 and
                      plan.get('execution_enabled') is True,'A runnable versioned batch plan is required.')
            check_id=secrets.token_hex(32);self._checks[check_id]=copy.deepcopy(plan)
            return dict(plan,check_id=check_id)

    @staticmethod
    def _batch_job(job):return job['plan'].get('kind')==B.CHECKED_KIND

    def _inspect(self,job):
        return (B.inspect if self._batch_job(job) else catalog_backend().inspect if self._catalog_job(job) else W.inspect)(job['name'],self.root)

    def start(self,check_id):
        with self._lock:
            W.require(type(check_id) is str and check_id in self._checks,'Check this configuration before Start.')
            plan=self._checks[check_id]
            W.require(plan.get('kind') in (W.KIND,CATALOG_KIND,B.CHECKED_KIND),'A preview is not an execution Check token.')
            if self._batch_job({'plan':plan}):
                W.require(plan.get('schema_version')==3 and plan.get('execution_enabled') is True,
                          'Batch execution requires a runnable versioned checked plan.')
            self._idle()
            # Reconstruct the complete trusted plan; rehashed browser edits are not authority.
            resolver=self._batch_resolver if plan.get('kind')==B.CHECKED_KIND else (self._catalog_resolver or catalog_backend().check) if plan.get('kind')==CATALOG_KIND else self._resolver
            actual=resolver(plan['resolved']['selection'],root=self.root)
            W.require(W.encoded(actual)==W.encoded(plan),'Inputs, settings or runtime changed after Check.')
            name=plan['resolved']['selection']['name']
            W.require(not any(j['name'].casefold()==name.casefold() for j in self._jobs),'This run name is already recorded.')
            job={'id':secrets.token_hex(16),'name':name,'status':'dispatch_uncertain','plan':plan,
                 'created_utc':W.utc(),'driver':None,'mode':'run'}
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(plan,self.root)
                L.reserve(job,self.root)
                self._jobs.append(job);self._persist();self._checks.pop(check_id)
            return self._launch(job)

    def _launch(self,job):
        self._active=job['id'];thread=threading.Thread(target=self._work,args=(job,),daemon=True,name='workflow-'+job['id'])
        thread.start();return self._view(job)

    def _spawn(self,argv,log,on_spawn):
        env=dict(os.environ,PYTHONDONTWRITEBYTECODE='1')
        try:stream=log.open('xb')
        except BaseException as error:
            on_spawn.preparation_failed(error);raise
        with stream:
            # Persist uncertainty BEFORE entering Popen. Even Popen OSError can
            # follow child creation; exception class is never nonlaunch proof.
            on_spawn.before_popen()
            p=subprocess.Popen(argv,cwd=self.root,env=env,stdin=subprocess.DEVNULL,stdout=stream,stderr=subprocess.STDOUT,
                               shell=False,creationflags=subprocess.CREATE_NO_WINDOW if os.name=='nt' else 0)
            on_spawn.popen_returned()
            on_spawn(p.pid,process_identity(p.pid));return p.wait()

    def _work(self,job):
        launch_lease=None;launcher_entered=False;preparing=False
        def release_launch_lease():
            nonlocal launch_lease
            if launch_lease is not None:
                lease=launch_lease;launch_lease=None;lease.__exit__(None,None,None)
        try:
            # Keep reconciliation/CLI excluded until the durable irreversible
            # boundary, or until pre-Popen failure evidence is sealed. The child
            # must be able to acquire this same lease for its identity handshake.
            lease=W.execution_lease(self.root);lease.__enter__();launch_lease=lease
            with self._lock:
                saved=W.read(self._state_path)
                current=next((j for j in saved['jobs'] if j.get('id')==job['id']),None)
                W.require(current and current['status'] in ACTIVE and W.encoded(current)==W.encoded(job),
                          'The durable launch reservation changed before worker preparation.')
                L.event(job,self.root,'preparing');preparing=True
            plan_path=safe_path(self.root,STATE+'/workflow-plans/'+job['id']+'.json')
            if job['mode'] in ('run','continue'):W.write(plan_path,job['plan'],fresh=True)
            log=safe_path(self.root,STATE+'/workflow-logs/'+job['id']+'.log');log.parent.mkdir(parents=True,exist_ok=True)
            mode=job['mode']+'-batches' if self._batch_job(job) else job['mode']+'-catalog' if self._catalog_job(job) else job['mode']
            argv=[sys.executable,'-B',str(self.root/'tools/scenario_workflow.py'),mode]
            if Path(sys.executable).name.casefold()=='pvpython.exe':argv[1:1]=['--no-mpi','--disable-registry']
            argv+=['--plan',str(plan_path)] if job['mode'] in ('run','continue') else ['--name',job['name']]
            argv+=['--dispatch-id',job['id']]
            def spawned(pid,identity):
                with self._lock:
                    job.update(driver={'pid':pid,'identity':identity},status='running');self._persist()
                release_launch_lease()
            def before_popen():
                L.event(job,self.root,'popen-entered')
                release_launch_lease()
            spawned.before_popen=before_popen
            spawned.popen_returned=lambda:L.event(job,self.root,'popen-returned')
            def preparation_failed(error):
                with self._lock:L.failure(job,self.root,error,managed_launcher=True)
            spawned.preparation_failed=preparation_failed
            L.event(job,self.root,'launcher');launcher_entered=True
            code=self._launcher(argv,log,spawned)
            release_launch_lease()
            with self._lock:
                directory=W.run_path(job['name'],self.root)
                receipt=W.read(directory/'run.json') if (directory/'run.json').exists() else None
                if code==0 and receipt and receipt['status'] in (*W.TERMINAL,'stopped'):
                    if receipt['status'] in W.TERMINAL:
                        self._inspect(job)
                    job['status']=receipt['status'];job.pop('error',None)
                else:
                    job.update(status='dispatch_uncertain',error='The workflow did not return verified terminal or stopped stages. Retain output and inspect possible nested workers.')
                    if not self._catalog_job(job) and not self._batch_job(job):I.capture(job,self.root)
                self._persist()
        except BaseException as error:
            with self._lock:
                if preparing and not launcher_entered:
                    try:L.failure(job,self.root,error)
                    except (OSError,ValueError,KeyError,TypeError,ControlError):pass
                job.update(status='dispatch_uncertain',error=str(error));self._persist()
        finally:
            release_launch_lease()
            with self._lock:self._active=None

    def stop(self,name):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None);W.require(job is not None,'Unknown owned run.')
            W.require(job['status'] in ('running','stop_requested'),'The run has no active committed stage yet.')
            directory=W.run_path(name,self.root);path=directory/'STOP.json'
            W.require((directory/'run.json').is_file() and W.read(directory/'run.json')['status']=='running',
                      'Wait for the first committed run receipt before requesting Stop.')
            if self._batch_job(job):
                if not path.exists():B.request_stop(name,self.root)
            elif not path.exists():W.write(path,{'requested_utc':W.utc()},fresh=True)
            job['status']='stop_requested';self._persist();return self._view(job)

    def resume(self,name):
        with self._lock:
            self._idle();job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and job['status']=='stopped','Only this interface\'s stage-boundary stopped runs can resume.')
            (B.admit if self._batch_job(job) else catalog_backend().admit if self._catalog_job(job) else W.admit)(job['plan'],self.root,resume=True)
            # New dispatch/log identity; selected settings are the preserved plan.
            with W.execution_lease(self.root):
                W.verify_dispatch_reservations(job['plan'],self.root)
                for key in ('launch_intent_sha256','launch_failure_sha256','launch_recovery_sha256','launch_verified_boundary'):
                    job.pop(key,None)
                job.update(id=secrets.token_hex(16),status='dispatch_uncertain',driver=None,mode='resume')
                L.reserve(job,self.root)
                self._persist()
            return self._launch(job)

    def verify(self,name):
        with self._lock:
            W.require(self._active is None and not self._peer_busy(),'Wait for active work before verifying saved execution.')
            with W.execution_lease(self.root):
                saved=W.read(self._state_path)
                W.require(saved.get('kind')=='local_workflow_jobs_v1' and type(saved.get('jobs')) is list,
                          'Saved launch reservations are unsupported.')
                job=next((j for j in saved['jobs'] if j.get('name')==name),None);W.require(job is not None,'Unknown owned run.')
                recovered=bool(job.get('launch_recovery_sha256'))
                inspected_stamps=L.boundary_stamps(job,self.root)[1] if recovered else None
                receipt=self._inspect(job)
                W.require(receipt['configuration_sha256']==job['plan']['configuration_sha256'],'Saved run differs from owned plan.')
                stopped=receipt.get('status')=='stopped' and (self._batch_job(job) and receipt.get('resume_allowed') is True and
                        receipt.get('verification')=='sealed_prefix_verified' or recovered and not self._batch_job(job))
                if stopped and not self._batch_job(job):W.verify_checkpoint(W.run_path(name,self.root),receipt,self.root)
                W.require(receipt['status'] in W.TERMINAL or stopped,'Run has no verified completion or saved boundary; incomplete evidence is retained.')
                W.require(W.identity_ended(job.get('driver')),'Owned driver is active or its lifetime is unknown.')
                if recovered:
                    W.require(job['mode']=='resume' and (stopped or receipt.get('verification')=='terminal_artifacts_verified'),
                              'A recovered Resume needs independent saved-output verification.')
                    L.known_ended(receipt.get('supervisor'))
                    job['launch_verified_boundary']=L.supersede(job,receipt,self.root,inspected_stamps=inspected_stamps)
                job.update(status=receipt['status']);job.pop('error',None)
                self._jobs=saved['jobs'];self._persist()
            return self._view(job)

    def inspect_failure(self,name):
        with self._lock:
            W.require(self._active is None and not W.lease_busy(self.root),'Wait for active work before inspecting a failed launch.')
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and not self._catalog_job(job) and not self._batch_job(job) and job['status']=='dispatch_uncertain',
                      'Only a recognized legacy denied launch can use this failure inspector.')
            with W.execution_lease(self.root):
                stamp=I.inspect_failure(job,self.root)
                job.update(status='inspected_failure',inspection_sha256=stamp);job.pop('error',None);self._persist()
            return self._view(job)

    def recover_launch(self,name):
        with self._lock:
            W.require(self._active is None and not self._peer_busy(),
                      'Wait for active work before checking a not-launched failure.')
            with W.execution_lease(self.root):
                # Reload under the shared lease: another reopened controller may
                # already have settled this attempt. Never overwrite its state.
                saved=W.read(self._state_path)
                W.require(saved.get('kind')=='local_workflow_jobs_v1' and type(saved.get('jobs')) is list,
                          'Saved launch reservations are unsupported.')
                job=next((j for j in saved['jobs'] if j.get('name')==name),None)
                W.require(job,'Unknown owned run.')
                if job.get('launch_recovery_sha256'):
                    L.verify_retirement(job,self.root)
                else:
                    W.require(job['status']=='dispatch_uncertain','Only a proved not-launched failure can be recovered.')
                    W.verify_dispatch_reservations(None,self.root,_not_launched_id=job['id'])
                    if job['mode']=='resume':
                        receipt=self._inspect(job)
                        W.require(receipt.get('status')=='stopped' and receipt.get('configuration_sha256')==job['plan']['configuration_sha256'] and
                                  (not self._batch_job(job) or receipt.get('resume_allowed') is True and receipt.get('verification')=='sealed_prefix_verified'),
                                  'The unchanged stopped boundary is not independently verified.')
                        if not self._batch_job(job):W.verify_checkpoint(W.run_path(name,self.root),receipt,self.root)
                    stamp,status=L.retire(job,self.root)
                    job.update(status=status,launch_recovery_sha256=stamp)
                    self._jobs=saved['jobs'];self._persist()
                self._jobs=saved['jobs']
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
                L.reserve(job,self.root)
                self._jobs.append(job);self._persist()
            return self._launch(job)

    def _view(self,job):
        out={k:copy.deepcopy(job[k]) for k in ('id','name','status','created_utc')}
        out['selection']=copy.deepcopy(job['plan']['resolved']['selection'])
        out['source_pose']=copy.deepcopy(job['plan']['resolved'].get('source_pose'))
        out['source_position_global_mm']=copy.deepcopy(job['plan']['resolved'].get('source_position_global_mm'))
        out['configuration_sha256']=job['plan']['configuration_sha256']
        out['output']=W.BASE+'/'+job['name'];out['error']=job.get('error');out['stages']={}
        out['workflow_kind']=job['plan'].get('kind')
        out['execution_contract']='serial_batches_v3' if self._batch_job(job) else 'legacy_v1'
        out['can_inspect_failure']=not self._catalog_job(job) and not self._batch_job(job)
        out['can_continue_prefix']=out['can_inspect_failure'] and R.eligible_name(job['name']) and job['status']=='dispatch_uncertain'
        out['can_finalize_results']=False
        out['can_recover_launch']=False
        out['can_verify_saved_execution']=job['mode']=='resume' and bool(job.get('launch_recovery_sha256')) and self._active is None
        if job['status']=='dispatch_uncertain' and self._active is None and job.get('launch_failure_sha256'):
            try:L.verify_failure(job,self.root,_recovered=(L.directory(job,self.root)/'recovery.json').exists());out['can_recover_launch']=True
            except (OSError,ValueError,KeyError,TypeError,ControlError):pass
        out['logs']=[]
        if self._batch_job(job):out['batching']=copy.deepcopy(job['plan']['resolved']['batching'])
        directory=W.run_path(job['name'],self.root)
        try:
            receipt=W.read(directory/'run.json');out['stages']=receipt['stages'];out['counts']=receipt.get('counts')
            out['can_finalize_results']=out['can_inspect_failure'] and job['status']=='dispatch_uncertain' and F.candidate(directory)
            if self._batch_job(job):
                out['batch_progress']={k:copy.deepcopy(receipt.get(k)) for k in
                    ('completed_batch_count','completed_primary_count','batch_count','active_batch_index','active_stage','resumes')}
                out['batch_progress']['status']=receipt.get('status')
                current=receipt.get('active_stage')
                if current and receipt.get('status')=='running':
                    out['stages'][current]={'status':'running'}
                for stage in B.SHARED:
                    file='logs/'+stage+'.log'
                    if safe_path(directory,file).is_file():out['logs'].append({'file':file,'label':stage.replace('_',' ')})
                index=receipt.get('active_batch_index')
                if index is None and receipt.get('completed_batch_count',0)>0:index=receipt['completed_batch_count']-1
                if type(index) is int:
                    for stage in B.BATCH_STAGES:
                        file=f'batches/b{index:010d}/logs/{stage}.log'
                        if safe_path(directory,file).is_file():out['logs'].append({'file':file,'label':f'batch {index} '+stage.replace('_',' ')})
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
            allowed_log=file in {stage+'.log' for stage in W.STAGES}
            if self._batch_job(job):allowed_log=bool(re.fullmatch(r'(?:logs/|batches/b[0-9]{10}/logs/)(?:geometry|native_preparation|radiation|event_ledger|response)\.log',file))
            if file.endswith('.log') and allowed_log:
                path=safe_path(directory,file)
                with path.open('rb') as stream:
                    stream.seek(max(0,path.stat().st_size-256*1024));body=stream.read(256*1024)
                return body,'text/plain; charset=utf-8'
            if self._batch_job(job):
                W.require(job['status'] in (*W.TERMINAL,'stopped'),'Use verified completed or stopped batch results.')
                path=B.artifact(name,file,self.root)
                W.require(path.stat().st_size<=64*1024*1024,'Artifact exceeds the browser size limit; use its retained local path.')
                mime='text/html; charset=utf-8' if file.endswith('.html') else 'text/plain; charset=utf-8' if file.endswith(('.csv','.jsonl')) else 'application/octet-stream' if file.endswith(('.lh5','.h5','.jld2')) else 'application/json; charset=utf-8'
                return path.read_bytes(),mime
            W.require(job['status'] in W.TERMINAL,'Verify completed results before downloading.')
            (catalog_backend().inspect(name,self.root) if self._catalog_job(job) else self._saved_verifier.inspect(name))
            complete=W.read(directory/'COMPLETE.json');W.require(file in complete['artifacts'] or file=='COMPLETE.json','Unsupported result artifact.')
            path=safe_path(directory,file);W.require(path.stat().st_size<=64*1024*1024,'Artifact exceeds the browser size limit.')
            mime='text/html; charset=utf-8' if file.endswith('.html') else 'text/plain; charset=utf-8' if file.endswith(('.csv','.jsonl')) else 'application/json; charset=utf-8'
            return path.read_bytes(),mime

    def event_page(self,name,batch_index,offset,limit):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and self._batch_job(job),'Unknown owned batch run.')
            W.require(job['status'] in (*W.TERMINAL,'stopped'),'Use completed batches from a sealed or stopped run.')
            reply=B.event_page(name,batch_index,offset,limit,self.root)
            W.require(reply.get('configuration_sha256')==job['plan']['configuration_sha256'],'Saved event page differs from the owned plan.')
            return reply

    def batch_waveforms(self,name,batch_index,primary_id,group_id):
        with self._lock:
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and self._batch_job(job) and job['status'] in (*W.TERMINAL,'stopped'),'Use a sealed owned event batch.')
            reply=B.focused_waveforms(name,batch_index,primary_id,group_id,self.root)
            W.require(reply.get('configuration_sha256')==job['plan']['configuration_sha256'],'Saved waveform differs from the owned plan.')
            return reply

    def result_options(self,name):
        """Read saved result presence; opening each export still verifies its inputs."""
        with self._lock:
            directory=W.run_path(name,self.root)
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and (job['status'] in W.TERMINAL or
                      self._batch_job(job) and job['status']=='stopped'),
                      'Use a completed owned run or stopped owned batch for saved results.')
            config_sha=job['plan']['configuration_sha256']
            W.require(type(config_sha) is str and re.fullmatch('[0-9a-f]{64}',config_sha),
                      'Saved result configuration identity is unsupported.')
            reply={'kind':'local_saved_result_options_v1','name':name,'configuration_sha256':config_sha,
                   'feature_export_present':False,'acquisition_export_present':False,
                   'spectrum_file':None,'spectrum_scope':None}
            if job['status']=='stopped':return reply
            for key,base in (('feature_export_present','.local/psd-features/'),
                             ('acquisition_export_present','.local/waveform-acquisition/')):
                reply[key]=safe_path(self.root,base+config_sha+'/bundle/COMPLETE.json').is_file()
            spectrum='results/histograms.json' if self._batch_job(job) else 'response/histograms.json'
            if safe_path(directory,spectrum).is_file():
                self.artifact(name,spectrum)
                reply.update(spectrum_file=spectrum,spectrum_scope='full_run')
            return reply

    def features(self,name,primary_id,group_id=None):
        """Verify a pre-exported derivative; no simulation, export or write on GET."""
        with self._lock:
            W.run_path(name,self.root)
            W.require(type(primary_id) is int and 0<=primary_id<=9007199254740991 and
                      (group_id is None or type(group_id) is int and 0<=group_id<=9007199254740991),
                      'Invalid exact feature identity.')
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and job['status'] in W.TERMINAL,'Use a completed owned run for saved features.')
            config_sha=job['plan']['configuration_sha256']
            W.require(type(config_sha) is str and re.fullmatch('[0-9a-f]{64}',config_sha),
                      'Saved feature configuration identity is unsupported.')
            backend=psd_backend()
            directory=safe_path(self.root,'.local/psd-features/'+config_sha+'/bundle')
            W.require(Path(backend.default_bundle_dir(self.root,config_sha))==directory,
                      'Saved feature directory differs from the canonical configuration.')
            reply={'kind':'local_saved_psd_features_v1','name':name,'configuration_sha256':config_sha,
                   'primary_id':primary_id,'group_id':group_id,'available':False,
                   'profile_sha256':None,'bundle_sha256':None,
                   'note':'Saved features are unavailable for this run. Opening this panel does not export features or start a simulation.'}
            if not directory.is_dir():return reply
            try:
                bundle=backend.load_bundle(directory,expected_config_sha256=config_sha,root=self.root,verify_inputs=True)
                record=backend.get_record(bundle,primary_id,group_id)
            except (OSError,ValueError,KeyError,TypeError,ControlError) as error:
                raise ControlError('Saved features could not be verified for this configuration and selection.') from error
            provenance=bundle['provenance']
            W.require(provenance['run_ref']==W.BASE+'/'+name,
                      'Saved feature inputs belong to another saved run.')
            reply.update(available=True,profile_sha256=provenance['profile_sha256'],
                         bundle_sha256=hashlib.sha256(backend.encoded(bundle)).hexdigest(),profile=bundle['profile'],
                         record=record,provenance=provenance,counts=bundle['counts'],
                         note='Saved full-resolution waveform derivation. Feature eligibility is separate from readout acceptance and physical validation.')
            return reply

    def acquisition(self,name,primary_id,group_id=None):
        """Verify an existing acquisition bundle; no simulation or export on GET."""
        with self._lock:
            W.run_path(name,self.root)
            W.require(type(primary_id) is int and 0<=primary_id<=9007199254740991 and
                      (group_id is None or type(group_id) is int and 0<=group_id<=9007199254740991),
                      'Invalid exact acquisition identity.')
            job=next((j for j in self._jobs if j['name']==name),None)
            W.require(job and job['status'] in W.TERMINAL,'Use a completed owned run for saved acquisition.')
            config_sha=job['plan']['configuration_sha256']
            W.require(type(config_sha) is str and re.fullmatch('[0-9a-f]{64}',config_sha),
                      'Saved acquisition configuration identity is unsupported.')
            backend=acquisition_backend()
            directory=safe_path(self.root,'.local/waveform-acquisition/'+config_sha+'/bundle')
            W.require(Path(backend.default_bundle_dir(self.root,config_sha))==directory,
                      'Saved acquisition directory differs from the canonical configuration.')
            reply={'kind':'local_saved_waveform_acquisition_v1','name':name,'configuration_sha256':config_sha,
                   'primary_id':primary_id,'group_id':group_id,'available':False,
                   'profile_sha256':None,'bundle_sha256':None,'source_features_manifest_sha256':None,'source_profile_sha256':None,
                   'note':'Saved acquisition is unavailable for this run. Opening this panel does not export data or start a simulation.'}
            if not directory.is_dir():return reply
            try:
                bundle=backend.load_bundle(directory,expected_config_sha256=config_sha,root=self.root,verify_inputs=True)
                provenance=bundle['provenance']
                W.require(provenance['run_ref']==W.BASE+'/'+name,'Saved acquisition inputs belong to another saved run.')
                W.require(provenance['source_features_ref']=='.local/psd-features/'+config_sha+'/bundle',
                          'Saved acquisition source features differ from the canonical configuration.')
                for key in ('profile_sha256','source_features_manifest_sha256','source_profile_sha256'):
                    W.require(type(provenance[key]) is str and re.fullmatch('[0-9a-f]{64}',provenance[key]),
                              'Saved acquisition source or profile identity is unsupported.')
                record=backend.get_record(bundle,primary_id,group_id)
            except (OSError,ValueError,KeyError,TypeError,ControlError) as error:
                raise ControlError('Saved acquisition could not be verified for this configuration and selection.') from error
            reply.update(available=True,profile_sha256=provenance['profile_sha256'],
                         bundle_sha256=hashlib.sha256(backend.encoded(bundle)).hexdigest(),
                         source_features_manifest_sha256=provenance['source_features_manifest_sha256'],
                         source_profile_sha256=provenance['source_profile_sha256'],profile=bundle['profile'],
                         calibrations=bundle['calibrations'],record=record,provenance=provenance,counts=bundle['counts'],
                         note='Saved synthetic acquisition with independent injection calibration. Original feature and readout eligibility remain distinct.')
            return reply

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
            (catalog_backend().inspect(name,self.root) if self._catalog_job(job) else self._saved_verifier.inspect(name))
            return reply
