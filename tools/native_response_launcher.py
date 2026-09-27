"""Detached native-only worker; Julia owns per-group checkpoints and the compute lock."""
import argparse, ctypes, json, os, shutil, subprocess, sys, time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
JULIA=Path.home()/'.julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe'
def read(path):return json.loads(path.read_text(encoding='utf-8-sig'))
def save(path,value):
    temp=path.with_name(path.name+'.tmp-'+str(os.getpid()))
    with temp.open('w',encoding='utf-8') as f:
        json.dump(value,f,indent=2);f.flush();os.fsync(f.fileno())
    os.replace(temp,path)
def take_lock(path):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CreateFileW.argtypes=[ctypes.c_wchar_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p,ctypes.c_uint32,ctypes.c_uint32,ctypes.c_void_p]
    api.CreateFileW.restype=ctypes.c_void_p
    handle=api.CreateFileW(str(path),0xc0000000,0,None,4,0x80,None)
    if handle==ctypes.c_void_p(-1).value:raise RuntimeError('An existing native worker owns the lock; do not restart')
    return handle

def release(handle):
    api=ctypes.WinDLL('kernel32',use_last_error=True)
    api.CloseHandle.argtypes=[ctypes.c_void_p];api.CloseHandle(handle)
def checked(path):
    path=path.resolve()
    if not path.is_relative_to(ROOT/'.local') or not (path/'config.json').is_file():raise ValueError('Prepared local native campaign required')
    return path
def reconcile(directory,status,code):
    # Optional owner-scoped handoff only; a clean clone has no private state.
    state=ROOT/'.local/autonomy/state.json';lock=ROOT/'.local/autonomy/lock/owner.txt'
    if not state.exists() or not lock.exists():return
    s=read(state);owner=s.get('owner')
    if owner!='chat-20260927-native-response-fix' or lock.read_text().strip()!=owner:return
    if s.get('last_native_path')!=directory.relative_to(ROOT).as_posix():return
    s.update(status='ready',owner=None,current_step=f'Native worker exited: {status}; code={code}',
             safe_next_step='Read native progress/COMPLETE and reuse saved results. Resume only unfinished groups; never Geant4.',
             worker_sessions=[],last_native_status=status,heartbeat_utc=time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()))
    save(state,s);lock.unlink()
    try:lock.parent.rmdir()
    except OSError:pass

def worker(directory,max_new):
    handle=take_lock(directory/'launcher.lock')
    stamp=str(time.time_ns());logdir=directory/'logs';logdir.mkdir(exist_ok=True)
    command=[str(JULIA),'--startup-file=no','--threads=2','--project=simulation',
             'simulation/native_checkpoint_batch.jl',str(directory)]
    if max_new is not None:command.append(str(max_new))
    env=dict(os.environ,OPENBLAS_NUM_THREADS='1',OMP_NUM_THREADS='1')
    try:
        with (logdir/(stamp+'.stdout.log')).open('xb') as stdout,(logdir/(stamp+'.stderr.log')).open('xb') as stderr:
            child=subprocess.Popen(command,cwd=ROOT,env=env,stdout=stdout,stderr=stderr,creationflags=subprocess.CREATE_NO_WINDOW)
            save(directory/'launcher.json',dict(pid=child.pid,wrapper_pid=os.getpid(),started_unix=time.time(),command=command,log=stamp))
            code=child.wait()
        status=read(directory/'progress.json').get('status') if (directory/'progress.json').exists() else 'no_progress'
        if code==0 and status not in ('paused','completed_with_native_failures','completed_native_response'):
            code=1
        save(logdir/(stamp+'.exit.json'),dict(exit_code=code,status=status,finished_unix=time.time()))
        reconcile(directory,status,code)
    finally:release(handle)
    return code
def start(directory,max_new=None):
    if (directory/'COMPLETE.json').exists():
        print('Already complete: inspect saved outputs; no computation started.');return
    for name in ('launcher.lock','worker.lock'):
        handle=take_lock(directory/name);release(handle)
    if shutil.disk_usage(directory).free<20*1024**3:raise RuntimeError('Need at least20GiB free; completed outputs are retained')
    command=[sys.executable,'--disable-registry','--no-mpi','-B',str(Path(__file__).resolve()),'worker',str(directory)]
    if max_new is not None:command+=['--max-new',str(max_new)]
    child=subprocess.Popen(command,cwd=ROOT,stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
        creationflags=subprocess.DETACHED_PROCESS|subprocess.CREATE_NEW_PROCESS_GROUP)
    print(json.dumps(dict(status='launched',wrapper_pid=child.pid,progress=str(directory/'progress.html'))))

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=('start','worker'));parser.add_argument('directory',type=Path)
    parser.add_argument('--max-new',type=int)
    args=parser.parse_args()
    if os.name!='nt':raise RuntimeError('Use the tested Windows environment')
    if args.max_new is not None and args.max_new<1:raise ValueError('Positive max-new required')
    directory=checked(args.directory)
    if args.action=='start':start(directory,args.max_new)
    else:sys.exit(worker(directory,args.max_new))
