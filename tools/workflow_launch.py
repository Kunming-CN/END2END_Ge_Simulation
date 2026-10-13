"""Durable proof for a dispatch that failed before invoking Popen.

Entering Popen is an irreversible uncertainty boundary, including an OSError.
Only this controller's preparation code may seal a not-invoked failure. Existing
opaque dispatches do not acquire authority from a missing driver or output root.
"""
import re
import scenario_workflow as W

STATE = '.local/local-control-v1'
KIND = 'workflow_launch_intent_v1'


def directory(job, root):
    return W.safe_path(root, STATE+'/workflow-launches/'+job['id'])


def auxiliary(job, root):
    return {key: W.safe_path(root, STATE+folder+job['id']+suffix)
            for key, folder, suffix in
            (('plan', '/workflow-plans/', '.json'), ('log', '/workflow-logs/', '.log'))}


def stamp(path):
    return {'sha256': W.sha(path), 'bytes': path.stat().st_size}


def output_boundary(job, root):
    output = W.run_path(job['name'], root)
    if job['mode'] != 'resume':
        W.require(not output.exists(), 'A not-launched dispatch cannot have a scientific output root.')
        return {'kind': 'absent_output_root'}
    # Resume retains its sealed boundary. Full stage/artifact inspection is also
    # required by the controller before a stopped status can be restored.
    stop = output/'STOP.json'
    return {'kind': 'stopped_boundary', 'run': stamp(output/'run.json'),
            'stop': stamp(stop) if stop.exists() else None}


def reserve(job, root):
    value = {'kind': KIND, 'dispatch_id': job['id'], 'name': job['name'],
             'mode': job['mode'], 'plan_sha256': W.digest(job['plan']),
             'created_utc': W.utc(), 'output_boundary': output_boundary(job, root)}
    path = directory(job, root)/'intent.json'
    W.write(path, value, fresh=True)
    job['launch_intent_sha256'] = W.sha(path)


def event(job, root, name):
    path = directory(job, root)/(name+'.json')
    W.write(path, {'kind': 'workflow_launch_boundary_v1', 'dispatch_id': job['id'],
                   'intent_sha256': job['launch_intent_sha256'],
                   'boundary': name, 'recorded_utc': W.utc()}, fresh=True)


def failure(job, root, error, *, managed_launcher=False):
    folder = directory(job, root)
    expected = {'intent.json', 'preparing.json'}
    if managed_launcher: expected.add('launcher.json')
    W.require({p.name for p in folder.iterdir()} == expected,
              'Launch crossed an unknown or process-creation boundary; retain the reservation.')
    value = {'kind': 'workflow_not_invoked_failure_v1', 'dispatch_id': job['id'],
             'intent_sha256': job['launch_intent_sha256'], 'recorded_utc': W.utc(),
             'boundary': 'managed_launcher_preparation' if managed_launcher else 'controller_preparation',
             'popen_invoked': False, 'error_type': type(error).__name__, 'error': str(error),
             'journal': {p.name: stamp(p) for p in folder.iterdir()},
             'auxiliary': {key: stamp(path) if path.exists() else None
                           for key, path in auxiliary(job, root).items()}}
    path = folder/'failure.json'; W.write(path, value, fresh=True)
    job['launch_failure_sha256'] = W.sha(path)


def verify_failure(job, root, *, _recovered=False, _historical_resume=False):
    W.require(job.get('driver') is None, 'A recorded or unknown worker cannot use not-launched recovery.')
    folder = directory(job, root); intent_path = folder/'intent.json'; failure_path = folder/'failure.json'
    W.require(W.sha(intent_path) == job.get('launch_intent_sha256') and
              W.sha(failure_path) == job.get('launch_failure_sha256'),
              'Not-launched authority is missing or changed.')
    intent = W.read(intent_path); failed = W.read(failure_path)
    W.require(intent.get('kind') == KIND and intent.get('dispatch_id') == job['id'] and
              intent.get('name') == job['name'] and intent.get('mode') == job['mode'] and
              intent.get('plan_sha256') == W.digest(job['plan']), 'Launch intent differs from the owned plan.')
    expected = {'intent.json', 'preparing.json'}
    boundary = failed.get('boundary')
    if boundary == 'managed_launcher_preparation': expected.add('launcher.json')
    W.require(boundary in ('managed_launcher_preparation', 'controller_preparation') and
              failed.get('kind') == 'workflow_not_invoked_failure_v1' and
              failed.get('dispatch_id') == job['id'] and
              failed.get('intent_sha256') == job['launch_intent_sha256'] and
              failed.get('popen_invoked') is False and set(failed.get('journal', {})) == expected and
              {p.name for p in folder.iterdir()} == expected | {'failure.json'} | ({'recovery.json'} if _recovered else set()) and
              type(failed.get('error')) is str and type(failed.get('error_type')) is str,
              'Process creation or an incomplete launch journal prevents recovery.')
    W.verify_inventory(folder, failed['journal'])
    for name in expected - {'intent.json'}:
        entry = W.read(folder/name)
        W.require(entry.get('kind') == 'workflow_launch_boundary_v1' and
                  entry.get('dispatch_id') == job['id'] and
                  entry.get('intent_sha256') == job['launch_intent_sha256'] and
                  entry.get('boundary')+'.json' == name, 'Launch boundary identity changed.')
    paths = auxiliary(job, root)
    W.require(set(failed.get('auxiliary', {})) == set(paths), 'Launch evidence inventory is unsupported.')
    for key, path in paths.items():
        expected_stamp = failed['auxiliary'][key]
        W.require((stamp(path) if path.exists() else None) == expected_stamp, 'Failed launch plan or log changed.')
    W.require(not _historical_resume or job['mode']=='resume', 'Only a recovered Resume can evolve to another verified boundary.')
    if not _historical_resume:
        W.require(output_boundary(job, root) == intent.get('output_boundary'),
                  'Scientific output or the saved stopped boundary changed after launch failure.')
    return failed


def retire(job, root):
    path = directory(job, root)/'recovery.json'
    failed = verify_failure(job, root, _recovered=path.exists())
    value = {'kind': 'workflow_not_invoked_recovery_v1', 'dispatch_id': job['id'],
             'failure_sha256': job['launch_failure_sha256'], 'retired_utc': W.utc(),
             'restored_status': 'stopped' if job['mode'] == 'resume' else 'launch_failed',
             'science_calls': 0, 'error': failed['error'],
             'action': 'Original evidence is preserved. Use a new run name, or Resume the unchanged sealed stopped boundary.'}
    if path.exists():
        saved = W.read(path)
        W.require(saved.get('kind') == value['kind'] and saved.get('dispatch_id') == job['id'] and
                  saved.get('failure_sha256') == value['failure_sha256'] and
                  saved.get('restored_status') == value['restored_status'] and
                  saved.get('science_calls') == 0 and saved.get('error') == failed['error'],
                  'An incomplete recovery record is inconsistent; preserve it for inspection.')
    else: W.write(path, value, fresh=True)
    return W.sha(path), value['restored_status']


def verify_recovery_history(job, root, *, historical_resume=False):
    path = directory(job, root)/'recovery.json'
    W.require(W.sha(path) == job.get('launch_recovery_sha256'), 'Launch recovery record changed.')
    recovered = W.read(path)
    # The recovery record is the sole permitted addition to the failure journal.
    folder = directory(job, root)
    failed = W.read(folder/'failure.json')
    W.require({p.name for p in folder.iterdir()} == set(failed['journal']) | {'failure.json', 'recovery.json'},
              'Unexpected launch evidence prevents reuse.')
    # Verify the original failure with its known, immutable recovery addition.
    verify_failure(job, root, _recovered=True, _historical_resume=historical_resume)
    W.require(recovered.get('kind') == 'workflow_not_invoked_recovery_v1' and
              recovered.get('dispatch_id') == job['id'] and
              recovered.get('failure_sha256') == job.get('launch_failure_sha256') and
              recovered.get('restored_status') == ('stopped' if job['mode'] == 'resume' else 'launch_failed') and
              recovered.get('science_calls') == 0, 'Launch retirement differs from the owned reservation.')
    return recovered


def known_ended(supervisor):
    W.require(type(supervisor) is dict and set(supervisor)=={'pid','identity'} and
              type(supervisor['pid']) is int and supervisor['pid']>0 and
              type(supervisor['identity']) is str and supervisor['identity'] not in ('','unknown') and
              W.identity_ended(supervisor), 'The saved execution supervisor is active, missing or unknown.')


def boundary_stamps(job, root):
    output=W.run_path(job['name'],root);run=W.read(output/'run.json');status=run.get('status')
    W.require(status in (*W.TERMINAL,'stopped') and run.get('configuration_sha256')==job['plan']['configuration_sha256'],
              'Only a verified completed or sealed stopped execution can replace a recovered Resume boundary.')
    known_ended(run.get('supervisor'))
    stop=output/'STOP.json'
    stamps={'run':stamp(output/'run.json'),'stop':stamp(stop) if stop.exists() else None}
    if status in W.TERMINAL:stamps['complete']=stamp(output/'COMPLETE.json')
    elif job['plan'].get('kind')=='local_scenario_batch_execution_v3':
        W.require(run.get('resume_allowed') is True,'The new batch boundary is not resumable.')
    else:
        checkpoint=run.get('checkpoint_id')
        W.require(type(checkpoint) is str and re.fullmatch('[0-9a-f]{32}',checkpoint),'The new stopped boundary has no checkpoint authority.')
        stamps['checkpoint']=stamp(W.safe_path(root,STATE+'/checkpoints/'+checkpoint+'.json'))
    return run,stamps


def verification_path(job, root, run_sha256):
    W.require(type(run_sha256) is str and re.fullmatch('[0-9a-f]{64}',run_sha256),'Invalid verified boundary identity.')
    identity=W.digest({'dispatch_id':job['id'],'run_sha256':run_sha256})
    return W.safe_path(root,STATE+'/workflow-boundaries/'+identity+'.json')


def supersede(job, receipt, root, *, inspected_stamps):
    """Called only after the controller's independent saved-output inspection.

    Preserve the original journal; the immutable new authority is stored beside
    it and binds the new run/completion or checkpoint, rather than the old STOP.
    """
    W.require(job['mode']=='resume' and job.get('launch_recovery_sha256'), 'Only a recovered Resume may supersede its stopped boundary.')
    verify_recovery_history(job,root,historical_resume=True)
    run,stamps=boundary_stamps(job,root)
    W.require(stamps==inspected_stamps and run['status']==receipt['status'] and run.get('supervisor')==receipt.get('supervisor'),
              'Saved execution changed during independent verification.')
    value={'kind':'workflow_verified_resume_boundary_v1','dispatch_id':job['id'],
           'recovery_sha256':job['launch_recovery_sha256'],'plan_sha256':W.digest(job['plan']),
           'status':run['status'],'supervisor':run['supervisor'],'artifacts':stamps}
    path=verification_path(job,root,stamps['run']['sha256'])
    if path.exists():W.require(W.encoded(W.read(path))==W.encoded(value),'The existing verified-boundary authority changed.')
    else:W.write(path,value,fresh=True)
    return {'run_sha256':stamps['run']['sha256'],'authority_sha256':W.sha(path)}


def verify_retirement(job, root):
    verified=job.get('launch_verified_boundary')
    recovered=verify_recovery_history(job,root,historical_resume=verified is not None)
    if verified is None:
        W.require(job['status']==recovered['restored_status'],'Launch retirement differs from the owned reservation.')
        return recovered
    W.require(type(verified) is dict and set(verified)=={'run_sha256','authority_sha256'},'Verified Resume boundary authority is unsupported.')
    path=verification_path(job,root,verified['run_sha256'])
    W.require(W.sha(path)==verified['authority_sha256'],'Verified Resume boundary authority changed.')
    value=W.read(path);run,stamps=boundary_stamps(job,root)
    W.require(value=={'kind':'workflow_verified_resume_boundary_v1','dispatch_id':job['id'],
              'recovery_sha256':job['launch_recovery_sha256'],'plan_sha256':W.digest(job['plan']),
              'status':job['status'],'supervisor':run['supervisor'],'artifacts':stamps} and
              run['status']==job['status'] and stamps['run']['sha256']==verified['run_sha256'],
              'Saved execution changed after independent boundary verification.')
    return value
