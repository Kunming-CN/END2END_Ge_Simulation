"""On-demand, read-only checks of Control and the existing locked runtimes."""
from concurrent.futures import ThreadPoolExecutor
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

from local_ui_jobs import existing_julia_environment, ControlError
import scenario_workflow as W


HOST_PROBE = r'''
import importlib,json,sys
result={'version':list(sys.version_info[:3]),'executable':sys.executable,'modules':{}}
for name in ('numpy','h5py','scipy','yaml'):
    try:
        module=importlib.import_module(name)
        result['modules'][name]={'status':'ready','detail':str(getattr(module,'__version__','import succeeded'))}
    except ImportError as error:
        result['modules'][name]={'status':'missing' if getattr(error,'name',None)==name else 'unavailable','detail':str(error)}
print(json.dumps(result))
'''

JULIA_PROBE = r'''
using TOML, Artifacts
project = TOML.parsefile(Base.active_project())
manifest = TOML.parsefile(joinpath(dirname(Base.active_project()), "Manifest.toml"))
missing = String[]
mismatch = String[]
versions = String[]
for (name, entries) in manifest["deps"], entry in entries
    source = Base.locate_package(Base.PkgId(Base.UUID(entry["uuid"]), name))
    if source === nothing || !isfile(source)
        push!(missing, name)
        continue
    end
    if name in keys(get(project, "compat", Dict()))
        expected = project["compat"][name]
        version = get(entry, "version", "unknown")
        push!(versions, name * "=" * version)
        startswith(expected, "=") && version != expected[2:end] && push!(mismatch, name)
    end
    artifacts = joinpath(dirname(dirname(source)), "Artifacts.toml")
    for (artifact, metadata) in Artifacts.select_downloadable_artifacts(artifacts)
        Artifacts.artifact_exists(Base.SHA1(metadata["git-tree-sha1"])) || push!(missing, name * ":" * artifact)
    end
end
println("version=", VERSION)
println("arch=", Sys.ARCH)
println("packages=", join(sort(versions), "; "))
println("missing=", join(sort(unique(missing)), ", "))
println("mismatch=", join(sort(unique(mismatch)), ", "))
'''

TRANSPORT_PROBE = r'''
import importlib,json,os,platform,subprocess,sys
from pathlib import Path
try:
    import scenario_source_portable as source
    prefix=Path(sys.prefix).resolve()
    if Path(os.environ.get('CONDA_PREFIX','')).resolve()!=prefix:
        raise ValueError('Active transport Python is outside the Pixi prefix')
    expected=source.MACOS_MANIFEST if platform.system()=='Darwin' else 'transport/pixi.toml'
    if Path(os.environ.get('PIXI_PROJECT_MANIFEST','')).resolve()!=source.ROOT/expected:
        raise ValueError('Transport is not using this project Pixi manifest')
    wanted=source.locked_packages()
    wanted.update(source.locked_packages(('scipy',)))
    for name,item in wanted.items():source.package_record(prefix,item)
    if platform.python_version()!=wanted['python']['version']:
        raise ValueError('Transport Python version differs from pixi.lock')
    for name in ('numpy','h5py','scipy','yaml'):importlib.import_module(name)
    versions=[]
    for executable,expected_version in (('remage','1.1.0'),('geant4-config','11.3.2')):
        path=source.shutil.which(executable)
        if path is None or not Path(path).resolve().is_relative_to(prefix):
            raise ValueError('missing locked executable: '+executable)
        reply=subprocess.run([path,'--version'],capture_output=True,text=True,timeout=3,check=False)
        actual=reply.stdout.strip()
        if reply.returncode or actual!=expected_version:
            raise ValueError(executable+' version differs from lock: '+actual)
        versions.append(executable+' '+actual)
    result={'status':'ready','detail':'Python '+platform.python_version()+'; '+', '.join(versions)+
            '; '+str(len(wanted))+' exact locked package records; NumPy/h5py/SciPy/PyYAML imported.'}
except ImportError as error:
    result={'status':'missing','detail':str(error)}
except (OSError,ValueError) as error:
    result={'status':'missing' if 'missing' in str(error).lower() else 'mismatch','detail':str(error)}
except subprocess.TimeoutExpired:
    result={'status':'unavailable','detail':'A transport version probe timed out; no simulation was started.'}
print(json.dumps(result))
'''


def _item(item_id, label, status, detail, action='', *, required=True):
    return {'id': item_id, 'label': label, 'status': status, 'detail': detail,
            'action': action, 'required': required}


def _text(value):
    if isinstance(value, str):
        return value.replace('\x00', '').strip('\ufeff \r\n')
    return value.decode('utf-16-le' if b'\x00' in value else 'utf-8-sig', errors='replace').strip()


def _run(argv, root, runner, *, timeout=15):
    env = dict(os.environ, PYTHONDONTWRITEBYTECODE='1', OPENBLAS_NUM_THREADS='1',
               OMP_NUM_THREADS='1', JULIA_PKG_OFFLINE='true', JULIA_PKG_PRECOMPILE_AUTO='0', JULIA_NUM_THREADS='1')
    reply = runner(argv, cwd=root, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                   timeout=timeout, shell=False,
                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    if reply.returncode:
        raise ValueError((_text(reply.stderr) or _text(reply.stdout) or 'Command returned '+str(reply.returncode))[:1800])
    return _text(reply.stdout)


def _host(root, runner):
    prefix = [sys.executable]
    if Path(sys.executable).name.casefold() in ('pvpython', 'pvpython.exe'):
        prefix += ['--no-mpi', '--disable-registry']
    action = 'Use an existing Python 3.10+ with NumPy, or install NumPy into the selected interpreter. See /guide.html#requirements.'
    try:
        data = json.loads(_run(prefix+['-B', '-c', HOST_PROBE], root, runner, timeout=10))
        version = '.'.join(map(str, data['version']))
        result = [_item('host_python', 'Control Python 3.10+', 'ready' if data['version'] >= [3,10,0] else 'mismatch',
                        version+' · '+data['executable'], action)]
        for name, label in (('numpy','NumPy'), ('h5py','h5py'), ('scipy','SciPy'), ('yaml','PyYAML')):
            record = data['modules'][name]
            required = name == 'numpy'
            result.append(_item('host_'+name, 'Control Python · '+label+('' if required else ' (optional host analysis)'),
                                record['status'], record['detail'], action if required else
                                'Not required for the ordinary Control run. The transport/Pixi copy is checked separately.', required=required))
        return result
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        return [_item('host_python', 'Control Python 3.10+ and NumPy', 'unavailable', str(error), action)]


def _julia(root, runner, executable, mac):
    action = 'Prepare Julia 1.13.0 using the supplied simulation/Project.toml and Manifest.toml; see /guide.html#setup'+('-macos' if mac else '')+'.'
    try:
        if not executable:
            env = existing_julia_environment(dict(os.environ))
            executable = env.get('JULIA_EXE') or shutil.which('julia')
        if not executable:
            return [_item('julia_runtime', 'Julia 1.13.0 and installed packages', 'missing', 'Julia executable was not found.', action)]
        text = _run([executable, '--startup-file=no', '--history-file=no', '--compiled-modules=existing',
                     '--pkgimages=existing', '--project='+str(root/'simulation'), '-e', JULIA_PROBE], root, runner, timeout=25)
        data = dict(line.split('=',1) for line in text.splitlines() if '=' in line)
        version = data['version']
        native = not mac or data['arch'] == {'arm64':'aarch64','x86_64':'x86_64'}.get(platform.machine())
        runtime = _item('julia_runtime', 'Julia 1.13.0', 'ready' if version=='1.13.0' and native else 'mismatch',
                        version+' · '+data.get('arch','unknown architecture')+' · '+executable, action)
        missing, mismatch = data['missing'], data['mismatch']
        packages = _item('julia_packages', 'Julia packages and non-lazy artifacts',
                         'missing' if missing else 'mismatch' if mismatch else 'ready',
                         ('Missing: '+missing) if missing else ('Version mismatch: '+mismatch) if mismatch else data['packages'], action)
        return [runtime, packages]
    except ControlError as error:
        return [_item('julia_runtime', 'Julia 1.13.0 and installed packages', 'missing', str(error), action)]
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        return [_item('julia_runtime', 'Julia 1.13.0 and installed packages', 'unavailable', str(error), action)]


def _transport(root, runner, mac):
    action = 'Use Setup.command for the locked native macOS environment.' if mac else 'Follow /guide.html#setup: WSL2 Ubuntu-24.04, Pixi inside Ubuntu, then explicit pixi install --locked.'
    rows = []
    try:
        if mac:
            version = platform.mac_ver()[0]
            # The key is absent on Intel; -i then succeeds with an empty result.
            translated = _run(['/usr/sbin/sysctl','-in','sysctl.proc_translated'], root, runner)
            ready = bool(version) and int(version.split('.')[0]) >= 13 and translated != '1'
            rows.append(_item('macos_native', 'Native macOS 13+', 'ready' if ready else 'mismatch', version+' · '+platform.machine(), action))
            try:
                tools = _run(['/usr/bin/xcode-select', '-p'], root, runner, timeout=5)
                rows.append(_item('macos_build_tools', 'Apple Command Line Tools (exporter builds)', 'ready', tools, action, required=False))
            except (OSError, ValueError, subprocess.TimeoutExpired) as error:
                rows.append(_item('macos_build_tools', 'Apple Command Line Tools (exporter builds)', 'unavailable', str(error),
                                  'Run xcode-select --install before building exporters; see /guide.html#setup-macos.', required=False))
            pixi = os.environ.get('PIXI_EXECUTABLE') or shutil.which('pixi') or str(Path.home()/'.pixi/bin/pixi')
            if not Path(pixi).is_file():
                rows.append(_item('pixi', 'Native Pixi', 'missing', 'Pixi executable was not found.', action)); return rows
            pixi_version = _run([pixi,'--version'], root, runner)
        else:
            if shutil.which('wsl.exe') is None:
                return [_item('wsl', 'WSL2 · Ubuntu-24.04', 'missing', 'wsl.exe is unavailable.', action)]
            listing = _run(['wsl.exe','--list','--verbose'], root, runner, timeout=10)
            distro = next((parts for line in listing.splitlines()
                           if (parts := line.lstrip(' *\ufeff').split()) and parts[0]=='Ubuntu-24.04'), None)
            if not distro or distro[-1] != '2':
                return [_item('wsl', 'WSL2 · Ubuntu-24.04', 'missing' if not distro else 'mismatch',
                              'Ubuntu-24.04 is not installed in WSL2.', action)]
            script = '. /etc/os-release; printf "OS=%s|%s\\n" "$ID" "$VERSION_ID"; p="${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}"; if [ -x "$p" ]; then printf "PIXI="; "$p" --version; else printf "PIXI=MISSING\\n"; fi'
            text = _run(['wsl.exe','--distribution','Ubuntu-24.04','--exec','bash','-c',script], root, runner)
            data = dict(line.split('=',1) for line in text.splitlines() if '=' in line)
            rows.append(_item('wsl', 'WSL2 · Ubuntu-24.04', 'ready' if data.get('OS')=='ubuntu|24.04' else 'mismatch', data.get('OS','Ubuntu version unavailable'), action))
            pixi_version = data.get('PIXI','MISSING')
        if pixi_version == 'MISSING':
            rows.append(_item('pixi', 'Transport Pixi', 'missing', 'Pixi is missing in the selected transport runtime.', action)); return rows
        matched = re.search(r'(\d+)\.(\d+)\.(\d+)', pixi_version)
        supported = bool(matched) and (not mac or tuple(map(int,matched.groups())) >= (0,81,0))
        rows.append(_item('pixi', 'Transport Pixi', 'ready' if supported else 'mismatch', pixi_version, action))
        if not supported or any(row['status'] != 'ready' for row in rows if row['required']):
            return rows
        data = json.loads(_run(W.transport_prefix(root)+['python','-B','-c',TRANSPORT_PROBE], root, runner, timeout=20))
        rows.append(_item('transport_packages', 'Locked transport packages and Python modules', data['status'], data['detail'], action))
    except (OSError, ValueError, KeyError, subprocess.TimeoutExpired) as error:
        rows.append(_item('transport_packages', 'Locked transport packages and Python modules', 'unavailable', str(error), action))
    return rows


def inspect(root, *, runner=None, julia_executable=None):
    """Run only import/metadata/version probes; never install, compile or simulate."""
    root, runner = Path(root), runner or subprocess.run
    mac = sys.platform == 'darwin'
    with ThreadPoolExecutor(max_workers=3) as pool:
        tasks = (pool.submit(_host, root, runner), pool.submit(_julia, root, runner, julia_executable, mac),
                 pool.submit(_transport, root, runner, mac))
        prerequisites = [item for task in tasks for item in task.result()]
    return {'platform':'macos' if mac else 'windows' if os.name=='nt' else 'linux',
            'prerequisites':prerequisites,
            'ready':all(item['status']=='ready' for item in prerequisites if item['required']),
            'read_only':True, 'science_calls':0}
