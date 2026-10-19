"""Closed local Control adapter for existing sealed GeGI signal stores.

Discovery reads bounded project directories, never an inbound filesystem path.
The worker calls the saved-data Python entry directly under the existing shared
execution lease. It cannot launch radiation, carrier drift or calibration.
"""
from __future__ import annotations
import copy
from datetime import datetime, timezone
from pathlib import Path
import re
import secrets
import threading

import scenario_workflow as W
import gegi_calibration_admission as A
from local_ui_jobs import safe_path

STATE = '.local/local-control-v1/gegi-saved-jobs.json'
OUTPUTS = '.local/gegi-saved-reconstruction'
NAME = re.compile(r'[A-Za-z0-9][A-Za-z0-9_-]{0,47}\Z')
FILES = {'identity.json', 'summary.json', 'COMPLETE.json', 'progress.json'}


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _id(ref):
    return W.digest({'saved_gegi_input': ref})


def discover(root):
    """Only named import roots and immediate dataset/campaign siblings."""
    root=Path(root); local=safe_path(root,'.local'); campaigns={}; calibrations={}
    if not local.is_dir():
        return {'campaigns': [], 'calibrations': []}
    candidates=[]
    for folder in local.iterdir():
        try:
            directory=safe_path(root,folder.relative_to(root).as_posix())
            if directory.is_dir():candidates.append(directory/'campaign')
        except (OSError,W.ControlError):
            continue
    imports=safe_path(root,'.local/gegi-saved-inputs/campaigns')
    if imports.is_dir():candidates.extend(imports.iterdir())
    calibration_candidates=[]
    for path in candidates:
        try:
            ref=path.relative_to(root).as_posix();path=safe_path(root,ref)
            if not path.is_dir() or not (path/'COMPLETE.json').is_file() or not (path/'chunks').is_dir():continue
            complete=W.read(safe_path(path,'COMPLETE.json'))
            if complete.get('kind')!='gegi_campaign_plan_v1' or complete.get('status') not in W.TERMINAL or type(complete.get('chunks')) is not dict or not complete['chunks']:continue
            key=_id(ref);campaigns[key]={'id':key,'label':ref,'relative_path':ref,
                'chunks':len(complete['chunks']),'status':complete['status']}
            calibration_candidates.extend(path.parent.iterdir())
        except (OSError,ValueError,KeyError,TypeError,W.ControlError):
            continue
    imports=safe_path(root,'.local/gegi-saved-inputs/calibrations')
    if imports.is_dir():calibration_candidates.extend(imports.iterdir())
    for path in calibration_candidates:
        try:
            ref=path.relative_to(root).as_posix();path=safe_path(root,ref)
            if not path.is_dir() or not safe_path(path,'depth-calibration.json').is_file() or not safe_path(path,'identity.json').is_file():continue
            key=_id(ref);calibrations[key]={'id':key,'label':ref,'relative_path':ref,
                'scope':'Saved modeled injection response; completeness is checked by reconstruction.'}
        except (OSError,ValueError,W.ControlError):
            continue
    return {'campaigns':sorted(campaigns.values(),key=lambda c:c['label']),
            'calibrations':sorted(calibrations.values(),key=lambda c:c['label'])}


class SavedGeGIControl:
    def __init__(self, workflow, *, runner=None):
        self.workflow=workflow;self.root=Path(workflow.root);self.runner=runner
        path=safe_path(self.root,STATE);self.jobs={}
        if path.is_file():
            saved=W.read(path)
            W.require(saved.get('kind')=='gegi_saved_control_v1' and type(saved.get('jobs')) is list,
                      'Saved GeGI derivative state needs inspection.')
            for job in saved['jobs']:
                W.require(type(job) is dict and NAME.fullmatch(str(job.get('name',''))) and
                          type(job.get('campaign_id')) is str and type(job.get('calibration_id')) is str,
                          'Invalid saved GeGI derivative identity.')
                if job.get('status') in ('running','stop_requested'):job['status']='interrupted'
                self.jobs[job['name']]=job

    def _persist(self):
        W.write(safe_path(self.root,STATE),{'kind':'gegi_saved_control_v1','jobs':list(self.jobs.values())})

    def options(self):
        with self.workflow._lock:
            for job in self.jobs.values():self._refresh_completion(job)
            return {'kind':'gegi_saved_options_v1',**discover(self.root),
                'jobs':[copy.deepcopy(j) for j in self.jobs.values()],
                'new_science_calls':0,'input_scope':'Completed sealed campaign SQLite stores only; standalone response/results.json is a different format.'}

    def _job(self,name):
        W.require(type(name) is str and NAME.fullmatch(name),'Choose a simple derivative name up to 48 characters.')
        W.run_path(name,self.root)
        W.require(name in self.jobs,'Unknown saved GeGI derivative.')
        return self.jobs[name]

    def _refresh_completion(self,job):
        """A bound COMPLETE receipt outranks an interrupted browser handoff."""
        directory=safe_path(self.root,job['output_path']);receipt=safe_path(directory,'COMPLETE.json')
        if not receipt.is_file():return
        complete=W.read(receipt);summary=safe_path(directory,'summary.json');identity=safe_path(directory,'identity.json')
        W.require(complete.get('kind')=='gegi_saved_reconstruction_v3' and
                  complete.get('status')=='completed_conditional_reconstruction' and
                  complete.get('summary_sha256')==W.sha(summary) and complete.get('identity_sha256')==W.sha(identity),
                  'Saved derivative completion binding changed; preserve its files for inspection.')
        bound=W.read(identity)
        W.require(bound.get('campaign_complete_sha256')==W.sha(safe_path(self.root,job['campaign_path']+'/COMPLETE.json')),
                  'Saved derivative belongs to a different original campaign seal.')
        job['status']=complete['status'];job.pop('error',None)

    def state(self,name):
        with self.workflow._lock:
            original=self._job(name);self._refresh_completion(original)
            job=copy.deepcopy(original);directory=safe_path(self.root,OUTPUTS+'/'+name)
            for filename,key in (('progress.json','progress'),('summary.json','summary')):
                path=safe_path(directory,filename)
                if path.is_file():job[key]=W.read(path)
            return job

    def start(self,campaign_id,calibration_id,name,*,resume=False):
        W.require(type(campaign_id) is str and type(calibration_id) is str and type(resume) is bool,
                  'Choose saved input identities and an explicit resume flag.')
        W.require(type(name) is str and NAME.fullmatch(name),'Choose a simple derivative name up to 48 characters.')
        W.run_path(name,self.root)
        with self.workflow._lock:
            self.workflow._idle();available=discover(self.root)
            campaign=next((c for c in available['campaigns'] if c['id']==campaign_id),None)
            calibration=None if calibration_id=='' else next((c for c in available['calibrations'] if c['id']==calibration_id),None)
            W.require(campaign is not None and (calibration_id=='' or calibration is not None),'Choose an offered completed campaign and saved calibration; arbitrary paths are refused.')
            output=safe_path(self.root,OUTPUTS+'/'+name)
            if resume:
                old=self._job(name)
                self._refresh_completion(old)
                W.require(old['campaign_id']==campaign_id and old['calibration_id']==calibration_id and
                          old['status'] in ('interrupted','failed','stopped_saved_reconstruction') and output.is_dir(),
                          'Resume keeps the original saved-data recipe and only an unfinished derivative.')
            else:W.require(name not in self.jobs and not output.exists(),'Preserve the existing derivative. Choose a new unused name or explicitly resume it.')
            admission=A.campaign(safe_path(self.root,campaign['relative_path']),
                safe_path(self.root,calibration['relative_path']) if calibration else None,root=self.root)
            reservation='gegi-saved-'+secrets.token_hex(16)
            job={'name':name,'campaign_id':campaign_id,'calibration_id':calibration_id,
                'campaign_path':campaign['relative_path'],'calibration_path':calibration['relative_path'] if calibration else None,
                'output_path':OUTPUTS+'/'+name,'status':'running','started_utc':_utc(),
                'calibration_admission':admission,
                'new_radiation_calls':0,'new_native_calls':0,'new_field_calls':0,'new_calibration_calls':0}
            self.jobs[name]=job;self.workflow._active=reservation;self._persist()
            thread=threading.Thread(target=self._work,args=(name,reservation,resume),daemon=True,name=reservation)
            try:thread.start()
            except Exception:
                self.workflow._active=None;job['status']='failed';job['error']='Saved-data worker did not start.';self._persist();raise
            return copy.deepcopy(job)

    def _work(self,name,reservation,resume):
        try:
            with W.execution_lease(self.root):
                job=self.jobs[name]
                runner=self.runner
                if runner is None:
                    from gegi_saved_reconstruction import process
                    runner=process
                value=runner(safe_path(self.root,job['campaign_path']),
                    safe_path(self.root,job['calibration_path']) if job['calibration_path'] else None,
                    safe_path(self.root,job['output_path']),resume=resume)
                with self.workflow._lock:
                    job['status']=value['status'];job['finished_utc']=_utc();job.pop('error',None)
        except Exception as error:
            with self.workflow._lock:
                job=self.jobs[name];job['status']='failed';job['error']=str(error);job['finished_utc']=_utc()
        finally:
            with self.workflow._lock:
                if self.workflow._active==reservation:self.workflow._active=None
                self._persist()

    def stop(self,name):
        with self.workflow._lock:
            job=self._job(name);W.require(job['status']=='running','Only a running saved-data derivative can stop at its next chunk boundary.')
            output=safe_path(self.root,job['output_path']);W.require(output.is_dir(),'Wait until the saved-data derivative creates its output directory.')
            path=safe_path(output,'stop.request')
            if not path.exists():path.write_text('Requested through protected local Control.\n',encoding='utf-8')
            job['status']='stop_requested';self._persist();return copy.deepcopy(job)

    def artifact(self,name,file):
        W.require(type(file) is str and file in FILES,'Choose a named saved derivative summary file.')
        with self.workflow._lock:
            job=self._job(name);path=safe_path(self.root,job['output_path']+'/'+file)
            W.require(path.is_file() and path.stat().st_size<=4*1024*1024,'Saved derivative summary file is unavailable or exceeds the browser limit.')
            return path.read_bytes()
