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
FILES = {'identity.json', 'summary.json', 'COMPLETE.json', 'progress.json', 'results.json'}
STANDALONE = 'local_gegi_workflow_v1'
STANDALONE_DERIVATIVE = 'gegi_standalone_saved_reconstruction_v3'


def _utc():
    return datetime.now(timezone.utc).isoformat(timespec='seconds')


def _id(ref):
    return W.digest({'saved_gegi_input': ref})


def _standalone_metadata(path):
    """Lightweight receipt checks; discovery never hashes the large result CSV/JSON."""
    complete=W.read(safe_path(path,'COMPLETE.json'))
    request=W.read(safe_path(path,'gegi-request.json'))
    receipt=W.read(safe_path(path,'response/run.json'))
    W.require(complete.get('kind')==STANDALONE and complete.get('status') in W.TERMINAL and
              receipt.get('kind')=='gegi_native_response_v1' and receipt.get('status') in W.TERMINAL and
              request.get('kind')=='gegi_native_request_v1' and
              complete.get('configuration_sha256')==request.get('configuration_sha256')==receipt.get('configuration_sha256') and
              safe_path(path,'response/results.json').is_file(),
              'Use a completed standalone GeGI run with its original native request and results.')
    return complete,request,receipt


def discover(root, *, standalone_names=()):
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
                'input_kind':'campaign','resume_supported':True,'stop_supported':True,
                'chunks':len(complete['chunks']),'status':complete['status']}
            calibration_candidates.extend(path.parent.iterdir())
        except (OSError,ValueError,KeyError,TypeError,W.ControlError):
            continue
    for name in standalone_names:
        try:
            path=W.run_path(name,root);complete,request,receipt=_standalone_metadata(path)
            ref=path.relative_to(root).as_posix();key=_id(ref)
            campaigns[key]={'id':key,'label':name+' · completed standalone run','relative_path':ref,
                'input_kind':'standalone','source_run_name':name,'status':complete['status'],
                'configuration_sha256':complete['configuration_sha256'],'counts':receipt['counts'],
                'resume_supported':False,'stop_supported':False,
                'capability_note':'Standalone reprocessing has no checkpoint or stop boundary. A failed attempt needs a new derivative name.'}
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
    def __init__(self, workflow, *, runner=None, standalone_runner=None):
        self.workflow=workflow;self.root=Path(workflow.root);self.runner=runner;self.standalone_runner=standalone_runner
        path=safe_path(self.root,STATE);self.jobs={};self._readers={}
        if path.is_file():
            saved=W.read(path)
            W.require(saved.get('kind')=='gegi_saved_control_v1' and type(saved.get('jobs')) is list,
                      'Saved GeGI derivative state needs inspection.')
            for job in saved['jobs']:
                W.require(type(job) is dict and NAME.fullmatch(str(job.get('name',''))) and
                          type(job.get('campaign_id')) is str and type(job.get('calibration_id')) is str,
                          'Invalid saved GeGI derivative identity.')
                if job.get('status') in ('running','stop_requested'):job['status']='interrupted'
                W.require(job.get('input_kind','campaign') in ('campaign','standalone'),'Unknown saved GeGI input kind.')
                self._capabilities(job)
                self.jobs[job['name']]=job

    @staticmethod
    def _capabilities(job):
        standalone=job.get('input_kind','campaign')=='standalone'
        job.update(input_kind='standalone' if standalone else 'campaign',
                   resume_supported=not standalone,stop_supported=not standalone)
        if standalone:
            job['capability_note']='Standalone reprocessing has no checkpoint or stop boundary. A failed attempt needs a new derivative name.'
        return job

    def _inputs(self):
        names=[j['name'] for j in self.workflow._jobs if j.get('plan',{}).get('kind')==STANDALONE and j.get('status') in W.TERMINAL]
        return discover(self.root,standalone_names=names)

    def _verified_standalone(self,job):
        name=job['source_run_name'];path=W.run_path(name,self.root)
        owner=next((j for j in self.workflow._jobs if j['name']==name and
                    j.get('plan',{}).get('kind')==STANDALONE and j.get('status') in W.TERMINAL),None)
        W.require(owner is not None and job['campaign_path']==path.relative_to(self.root).as_posix(),
                  'Use a completed GeGI run owned by this Control workspace.')
        from gegi_workflow import inspect
        verified=inspect(name,self.root)
        W.require(verified.get('verification')=='terminal_artifacts_verified' and
                  owner['plan']['configuration_sha256']==verified['configuration_sha256']==job['configuration_sha256'],
                  'Standalone GeGI input differs from its owned configuration.')
        return path

    def _persist(self):
        W.write(safe_path(self.root,STATE),{'kind':'gegi_saved_control_v1','jobs':list(self.jobs.values())})

    def options(self):
        with self.workflow._lock:
            for job in self.jobs.values():self._refresh_completion(job)
            return {'kind':'gegi_saved_options_v1',**self._inputs(),
                'jobs':[copy.deepcopy(j) for j in self.jobs.values()],
                'new_science_calls':0,'input_scope':'Completed sealed campaign stores and completed standalone GeGI runs owned by this Control workspace.'}

    def _job(self,name):
        W.require(type(name) is str and NAME.fullmatch(name),'Choose a simple derivative name up to 48 characters.')
        W.run_path(name,self.root)
        W.require(name in self.jobs,'Unknown saved GeGI derivative.')
        return self.jobs[name]

    def _refresh_completion(self,job):
        """A bound COMPLETE receipt outranks an interrupted browser handoff."""
        directory=safe_path(self.root,job['output_path']);receipt=safe_path(directory,'COMPLETE.json')
        if not receipt.is_file():return
        if job.get('input_kind')=='standalone':
            complete=W.read(receipt);identity=safe_path(directory,'identity.json')
            W.require(complete.get('kind')==STANDALONE_DERIVATIVE and
                      complete.get('status')=='completed_conditional_reconstruction' and
                      set(complete.get('files',{}))=={'identity.json','results.json'} and
                      complete['files']['identity.json']==W.sha(identity),
                      'Standalone derivative completion binding changed; preserve its files for inspection.')
            if job.get('derivative_complete_sha256'):
                W.require(W.sha(receipt)==job['derivative_complete_sha256'],'Standalone derivative completion receipt changed.')
            bound=W.read(identity)
            W.require(bound.get('kind')==STANDALONE_DERIVATIVE and
                      bound['original_input_sha256']['COMPLETE.json']==job['source_complete_sha256']==
                      W.sha(safe_path(self.root,job['campaign_path']+'/COMPLETE.json')),
                      'Standalone derivative belongs to a different original completion seal.')
            job.update(status=complete['status'],derivative_complete_sha256=W.sha(receipt),results_available=True,
                       files=['identity.json','results.json','COMPLETE.json'])
            if 'summary' not in job:
                # A completed processor receipt outranks an interrupted handoff.
                # Recovery reads only bounded headers, never the full aggregate.
                header=self._reader(job).summary()
                job['summary']={'status':complete['status'],'counts':header['counts'],
                                'signal_use_counts':header.get('signal_use_counts',{})}
            job.pop('error',None)
            return
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
            job['files']=[name for name in ('identity.json','progress.json','summary.json','results.json','COMPLETE.json')
                          if safe_path(directory,name).is_file()]
            return job

    def start(self,campaign_id,calibration_id,name,*,resume=False):
        W.require(type(campaign_id) is str and type(calibration_id) is str and type(resume) is bool,
                  'Choose saved input identities and an explicit resume flag.')
        W.require(type(name) is str and NAME.fullmatch(name),'Choose a simple derivative name up to 48 characters.')
        W.run_path(name,self.root)
        with self.workflow._lock:
            self.workflow._idle();available=self._inputs()
            campaign=next((c for c in available['campaigns'] if c['id']==campaign_id),None)
            calibration=None if calibration_id=='' else next((c for c in available['calibrations'] if c['id']==calibration_id),None)
            W.require(campaign is not None and (calibration_id=='' or calibration is not None),'Choose an offered completed GeGI input and saved calibration; arbitrary paths are refused.')
            standalone=campaign['input_kind']=='standalone'
            W.require(not standalone or not resume,'Standalone reprocessing does not support resume. Preserve the attempt and choose a new derivative name.')
            output=safe_path(self.root,OUTPUTS+'/'+name)
            if resume:
                old=self._job(name)
                self._refresh_completion(old)
                W.require(old['campaign_id']==campaign_id and old['calibration_id']==calibration_id and
                          old['status'] in ('interrupted','failed','stopped_saved_reconstruction') and output.is_dir(),
                          'Resume keeps the original saved-data recipe and only an unfinished derivative.')
            else:W.require(name not in self.jobs and not output.exists(),'Preserve the existing derivative. Choose a new unused name or explicitly resume it.')
            source=safe_path(self.root,campaign['relative_path'])
            calibration_path=safe_path(self.root,calibration['relative_path']) if calibration else None
            if standalone:
                self._verified_standalone({'campaign_path':campaign['relative_path'],
                    'source_run_name':campaign['source_run_name'],'configuration_sha256':campaign['configuration_sha256']})
                _,request,receipt=_standalone_metadata(source)
                admission=A.standalone(calibration_path,request,receipt,receipt['channels']) if calibration else None
            else:admission=A.campaign(source,calibration_path,root=self.root)
            reservation='gegi-saved-'+secrets.token_hex(16)
            job={'name':name,'campaign_id':campaign_id,'calibration_id':calibration_id,
                'campaign_path':campaign['relative_path'],'calibration_path':calibration['relative_path'] if calibration else None,
                'output_path':OUTPUTS+'/'+name,'status':'running','started_utc':_utc(),
                'calibration_admission':admission,
                'new_radiation_calls':0,'new_native_calls':0,'new_field_calls':0,'new_calibration_calls':0}
            if standalone:
                job.update(input_kind='standalone',source_run_name=campaign['source_run_name'],
                    configuration_sha256=campaign['configuration_sha256'],source_complete_sha256=W.sha(source/'COMPLETE.json'))
            self._capabilities(job)
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
                if job['input_kind']=='standalone':
                    runner=self.standalone_runner
                    if runner is None:
                        from gegi_standalone_reconstruction import postprocess
                        runner=postprocess
                    imaging=runner(safe_path(self.root,job['campaign_path']),safe_path(self.root,job['output_path']),
                           calibration=safe_path(self.root,job['calibration_path']) if job['calibration_path'] else None)
                    _,_,receipt=_standalone_metadata(safe_path(self.root,job['campaign_path']))
                    with self.workflow._lock:
                        job['summary']=self._standalone_summary(receipt['counts'],imaging)
                        self._refresh_completion(job)
                        value={'status':job['status']}
                else:
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
            job=self._job(name)
            W.require(job.get('input_kind','campaign')!='standalone','Standalone reprocessing has no stop boundary; it does not support stop or resume.')
            W.require(job['status']=='running','Only a running saved-data derivative can stop at its next chunk boundary.')
            output=safe_path(self.root,job['output_path']);W.require(output.is_dir(),'Wait until the saved-data derivative creates its output directory.')
            path=safe_path(output,'stop.request')
            if not path.exists():path.write_text('Requested through protected local Control.\n',encoding='utf-8')
            job['status']='stop_requested';self._persist();return copy.deepcopy(job)

    def artifact(self,name,file):
        W.require(type(file) is str and file in FILES,'Choose a named saved derivative summary file.')
        with self.workflow._lock:
            job=self._job(name)
            if job.get('input_kind')=='standalone':
                self._refresh_completion(job)
                W.require(job['status']=='completed_conditional_reconstruction' and file in ('identity.json','results.json','COMPLETE.json'),
                          'Choose a completed standalone derivative result, identity or completion file.')
                if file=='results.json':
                    self._verified_standalone(job)
                    self._standalone_result_path(job)
            path=safe_path(self.root,job['output_path']+'/'+file)
            limit=256*1024*1024 if file=='results.json' else 4*1024*1024
            W.require(path.is_file() and path.stat().st_size<=limit,'Saved derivative file is unavailable or exceeds the browser limit.')
            return path.read_bytes()

    @staticmethod
    def _standalone_summary(original_counts,imaging,signal_use_counts=None):
        counts=copy.deepcopy(original_counts)
        counts.update({key:imaging[key] for key in ('conditional_candidate_groups','conditional_candidates','validated_recovered_groups')})
        summary={'status':'completed_conditional_reconstruction','counts':counts,'imaging_status':imaging['status']}
        if signal_use_counts is not None:summary['signal_use_counts']=signal_use_counts
        return summary

    def _standalone_result_path(self,job):
        directory=safe_path(self.root,job['output_path']);complete=W.read(safe_path(directory,'COMPLETE.json'))
        path=safe_path(directory,'results.json')
        W.require(path.stat().st_size<=256*1024*1024 and W.sha(path)==complete['files']['results.json'],
                  'Saved standalone derivative result changed or exceeds the browser limit.')
        return path

    def _standalone_results(self,job):
        path=self._standalone_result_path(job)
        payload=W.read(path);_,_,original=_standalone_metadata(safe_path(self.root,job['campaign_path']))
        W.require(payload.get('kind')=='gegi_multichannel_results_v1' and
                  payload.get('configuration_sha256')==job['configuration_sha256'] and
                  payload['counts']==original['counts'] and payload['channels']==original['channels'],
                  'Standalone derivative model, original counts or electrode identities changed.')
        return payload

    def results(self,name):
        with self.workflow._lock:
            job=self._job(name)
            W.require(job.get('input_kind')=='standalone','Campaign derivatives retain their chunk results and summary; choose a standalone derivative for this viewer.')
            self._refresh_completion(job)
            W.require(job['status']=='completed_conditional_reconstruction','Open a completed standalone GeGI derivative.')
            self._verified_standalone(job)
            payload=self._standalone_results(job)
            return dict(payload,name=job['source_run_name'],saved_derivative_name=job['name'])

    def _reader(self,job):
        if job['name'] not in self._readers:
            from gegi_result_reader import Reader
            source=self._verified_standalone(job)
            directory=safe_path(self.root,job['output_path'])
            complete=W.read(safe_path(directory,'COMPLETE.json'))
            reader=Reader(safe_path(directory,'results.json'),complete['files']['results.json'],
                name=job['source_run_name'],configuration_sha256=job['configuration_sha256'],derivative=job['name'],
                seal_paths=[safe_path(directory,ref) for ref in ('COMPLETE.json','identity.json')]+
                           [safe_path(source,ref) for ref in ('COMPLETE.json','gegi-request.json','response/run.json')])
            _,_,original=_standalone_metadata(source)
            W.require(reader.index['header']['counts']==original['counts'] and
                      reader.index['header']['channels']==original['channels'],
                      'Standalone derivative original counts or electrode identities changed.')
            self._readers[job['name']]=reader
        return self._readers[job['name']]

    def browse(self,name,original_name,part,*,event_id=None,results_sha256=None):
        with self.workflow._lock:
            job=self._job(name)
            W.require(job.get('input_kind')=='standalone' and job.get('source_run_name')==original_name,
                      'Choose a standalone derivative belonging to this original GeGI run.')
            self._refresh_completion(job)
            W.require(job['status']=='completed_conditional_reconstruction','Open a completed standalone GeGI derivative.')
            reader=self._reader(job)
            if part=='summary':return reader.summary(results_sha256)
            if part=='event':return reader.event(event_id,results_sha256)
            W.require(part=='imaging','Unknown standalone GeGI result view.')
            return reader.imaging(results_sha256)
