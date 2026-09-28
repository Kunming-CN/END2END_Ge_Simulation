"""Resume the existing native campaign with display and contact-start fail-closed adapters."""
import argparse, hashlib, json, os, subprocess, sys, time
from pathlib import Path
import resume_native_progress as base
old=base.old; ROOT=old.ROOT
ENTRY='simulation/native_contact_start_resilience.jl'
PROGRESS_ENTRY='simulation/native_progress_resilience.jl'
OWNER='chat-20260928-native-contact-start'
def digest(path):
    with path.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()
def exclusive_json(path,value):
    with path.open('x',encoding='utf-8') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
def bind(directory):
    prior=directory/'progress-recovery.json'
    if not prior.exists():raise ValueError('Validated progress recovery binding is required')
    names=(ENTRY,PROGRESS_ENTRY,'tools/resume_native_progress.py','tools/resume_native_contact.py')
    value={'kind':'native_contact_start_extension_v1',
           'config_sha256':digest(directory/'config.json'),
           'progress_recovery_sha256':digest(prior),
           'source_sha256':{n:digest(ROOT/n) for n in names},
           'scope':'Fail closed on saved positive deposits inside SSD contacts; original runner/checkpoints unchanged'}
    path=directory/'contact-start-recovery.json'
    if path.exists():
        if old.read(path)!=value:raise ValueError('Contact-start extension changed; inspect before resume')
    else:exclusive_json(path,value)
    return value
def reconcile(directory,status,code):
    state=ROOT/'.local/autonomy/state.json';lock=ROOT/'.local/autonomy/lock/owner.txt'
    if not state.exists() or not lock.exists():return
    s=old.read(state)
    if s.get('owner')!=OWNER or lock.read_text().strip()!=OWNER:return
    s.update(status='ready',owner=None,worker_sessions=[],last_native_status=status,
             current_step=f'Native contact-safe worker exited: {status}; code={code}',
             safe_next_step='Inspect COMPLETE/results; resume unfinished groups only. Never rerun Geant4.',
             heartbeat_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    if base.display_json(state,s):
        lock.unlink()
        try:lock.parent.rmdir()
        except OSError:pass

def worker(directory,max_new,handoff):
    lock=old.take_lock(directory/'launcher.lock')
    try:
        extension=bind(directory);stamp=str(time.time_ns());logs=directory/'logs';logs.mkdir(exist_ok=True)
        command=[str(old.JULIA),'--startup-file=no','--threads=2','--project=simulation',ENTRY,str(directory)]
        if max_new is not None:command.append(str(max_new))
        start={'command':command,'extension':extension,'started_unix':time.time(),'log':stamp}
        exclusive_json(logs/(stamp+'.start.json'),start)
        with (logs/(stamp+'.stdout.log')).open('xb') as stdout,(logs/(stamp+'.stderr.log')).open('xb') as stderr:
            child=subprocess.Popen(command,cwd=ROOT,stdout=stdout,stderr=stderr,
                env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1'),
                creationflags=subprocess.CREATE_NO_WINDOW)
            start.update(pid=child.pid,wrapper_pid=os.getpid())
            code,metadata_error=base.wait_with_display(child,directory,start)
        complete=directory/'COMPLETE.json'
        if code!=0:status='failed'
        elif complete.exists():
            result=old.read(complete)
            if result.get('config_hash')!=extension['config_sha256']:raise ValueError('Wrong completion config')
            status=result['status']
        else:status='paused'
        receipt={'exit_code':int(code),'status':status,'pid':child.pid,'finished_unix':time.time(),
                 'metadata_error':metadata_error,
                 'note':'Numeric exit and scientific checkpoints are authoritative; display files may be stale'}
        exclusive_json(logs/(stamp+'.exit.json'),receipt)
        if handoff:reconcile(directory,status,code)
        return code
    finally:old.release(lock)

def start(directory,max_new,handoff):
    if (directory/'COMPLETE.json').exists():
        print('Already complete; no process started.');return
    for name in ('launcher.lock','worker.lock'):
        h=old.take_lock(directory/name);old.release(h)
    if old.shutil.disk_usage(directory).free<20*1024**3:raise RuntimeError('Less than20GiB free; data preserved')
    bind(directory)
    command=[sys.executable,'--disable-registry','--no-mpi','-B',
             str(Path(__file__).resolve()),'worker',str(directory)]
    if max_new is not None:command+=['--max-new',str(max_new)]
    if handoff:command.append('--handoff')
    child=subprocess.Popen(command,cwd=ROOT,creationflags=subprocess.CREATE_NEW_CONSOLE)
    print(json.dumps({'status':'launched','wrapper_pid':child.pid,'progress':str(directory/'progress.html')}))

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('action',choices=('start','worker'));p.add_argument('directory',type=Path)
    p.add_argument('--max-new',type=int);p.add_argument('--handoff',action='store_true')
    a=p.parse_args()
    if os.name!='nt':raise RuntimeError('Use Windows')
    if a.max_new is not None and a.max_new<0:raise ValueError('max-new must be nonnegative')
    directory=old.checked(a.directory)
    if a.action=='start':start(directory,a.max_new,a.handoff)
    else:sys.exit(worker(directory,a.max_new,a.handoff))
