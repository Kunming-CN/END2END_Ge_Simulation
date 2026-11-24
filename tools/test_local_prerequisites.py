"""Read-only prerequisite probes: precise failures and the existing locked paths."""
import contextlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import local_prerequisites as P


class Probes(unittest.TestCase):
    root=Path(__file__).resolve().parents[1]

    def runner(self,output,returncode=0):
        calls=[]
        def run(argv,**kwargs):
            calls.append((argv,kwargs))
            self.assertFalse(kwargs['shell'])
            self.assertGreater(kwargs['timeout'],0)
            self.assertLessEqual(kwargs['timeout'],25)
            self.assertEqual(kwargs['env']['PYTHONDONTWRITEBYTECODE'],'1')
            self.assertEqual(kwargs['env']['JULIA_PKG_OFFLINE'],'true')
            return subprocess.CompletedProcess(argv,returncode,output,b'probe failed' if returncode else b'')
        return run,calls

    def test_host_numpy_is_required_optional_analysis_modules_are_separate(self):
        data={'version':[3,12,7],'executable':'selected Python','modules':{
            name:{'status':'ready' if name=='numpy' else 'missing','detail':name}
            for name in ('numpy','h5py','scipy','yaml')}}
        run,calls=self.runner(json.dumps(data).encode())
        rows=P._host(self.root,run)
        self.assertTrue(all(row['status']=='ready' for row in rows if row['required']))
        self.assertEqual([row['id'] for row in rows if row['required']],['host_python','host_numpy'])
        self.assertEqual(calls[0][0][0],sys.executable)
        data['modules']['numpy']['status']='missing'
        run,_=self.runner(json.dumps(data).encode())
        self.assertFalse(all(row['status']=='ready' for row in P._host(self.root,run) if row['required']))

    def test_julia_checks_exact_version_and_missing_installed_packages(self):
        output=b'version=1.13.0\narch=x86_64\npackages=SolidStateDetectors=0.11.8\nmissing=\nmismatch=\n'
        run,calls=self.runner(output)
        rows=P._julia(self.root,run,'pinned-julia',False)
        self.assertEqual([row['status'] for row in rows],['ready','ready'])
        argv=calls[0][0]
        self.assertIn('--compiled-modules=existing',argv)
        self.assertIn('--pkgimages=existing',argv)
        self.assertNotIn('Pkg.dependencies',P.JULIA_PROBE)
        self.assertNotIn('using SolidStateDetectors',P.JULIA_PROBE)
        for change,status,index in ((b'version=1.13.0',b'version=1.12.5',0),
                                    (b'missing=\n',b'missing=SSD:artifact\n',1),
                                    (b'mismatch=\n',b'mismatch=Unitful\n',1)):
            run,_=self.runner(output.replace(change,status))
            self.assertNotEqual(P._julia(self.root,run,'pinned-julia',False)[index]['status'],'ready')

    def test_julia_timeout_is_unavailable_with_no_retry(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            raise subprocess.TimeoutExpired(argv,kwargs['timeout'])
        rows=P._julia(self.root,run,'pinned-julia',False)
        self.assertEqual(rows[0]['status'],'unavailable');self.assertEqual(len(calls),1)

    def test_wsl_listing_handles_utf16_and_requires_version_two(self):
        with patch.object(P.shutil,'which',return_value='wsl.exe'):
            for version,status in (('1','mismatch'),('2','ready')):
                calls=[]
                def run(argv,**kwargs):
                    calls.append(argv)
                    output=('  NAME STATE VERSION\n* Ubuntu-24.04\tStopped\t'+version+'\n').encode('utf-16-le') if '--list' in argv else (
                        b'OS=ubuntu|24.04\nPIXI=pixi 0.55.0\n' if '-c' in argv and argv[-1]!=P.TRANSPORT_PROBE else
                        b'{"status":"ready","detail":"exact lock"}')
                    return subprocess.CompletedProcess(argv,0,output,b'')
                rows=P._transport(self.root,run,False)
                self.assertEqual(rows[0]['status'],status)
                if version=='1':self.assertEqual(len(calls),1)
                else:
                    self.assertEqual(rows[-1]['id'],'transport_packages')
                    self.assertEqual(calls[-1],P.W.transport_prefix(self.root)+['python','-B','-c',P.TRANSPORT_PROBE])

    def test_wsl_missing_pixi_and_denied_query_remain_specific(self):
        with patch.object(P.shutil,'which',return_value=None):
            self.assertEqual(P._transport(self.root,None,False)[0]['status'],'missing')
        with patch.object(P.shutil,'which',return_value='wsl.exe'):
            def run(argv,**kwargs):
                output=b'Ubuntu-24.04 Stopped 2' if '--list' in argv else b'OS=ubuntu|24.04\nPIXI=MISSING\n'
                return subprocess.CompletedProcess(argv,0,output,b'')
            self.assertEqual(P._transport(self.root,run,False)[-1]['status'],'missing')
            run,_=self.runner(b'',1)
            self.assertIn('probe failed',P._transport(self.root,run,False)[0]['detail'])

    def test_native_macos_uses_same_locked_wrapper_and_checks_rosetta(self):
        calls=[]
        def run(argv,**kwargs):
            calls.append(argv)
            output=(b'0' if 'sysctl.proc_translated' in argv else b'/Library/Developer/CommandLineTools' if '-p' in argv else
                    b'pixi 0.81.0' if '--version' in argv else b'{"status":"ready","detail":"native lock"}')
            return subprocess.CompletedProcess(argv,0,output,b'')
        with patch.object(P.platform,'mac_ver',return_value=('13.6.1',(),'')),patch.object(P.platform,'machine',return_value='arm64'),patch.object(P.shutil,'which',return_value='/pixi'),patch.object(P.Path,'is_file',return_value=True),patch.object(P.W,'transport_prefix',return_value=['native-workflow']):
            rows=P._transport(self.root,run,True)
            self.assertTrue(all(row['status']=='ready' for row in rows))
            self.assertEqual(calls[-1][0],'native-workflow')
            def translated(argv,**kwargs):
                if 'sysctl.proc_translated' in argv:return subprocess.CompletedProcess(argv,0,b'1',b'')
                return run(argv,**kwargs)
            rows=P._transport(self.root,translated,True)
            self.assertEqual(rows[0]['status'],'mismatch')
            self.assertNotEqual(rows[-1]['id'],'transport_packages')

    def test_transport_probe_uses_existing_exact_package_validator(self):
        checked=[]
        source=SimpleNamespace(ROOT=self.root,MACOS_MANIFEST='transport/macos/pixi.toml',
            locked_packages=lambda names=None:{'scipy' if names else 'python':{'name':'scipy' if names else 'python','version':'3.12.7'}},
            package_record=lambda prefix,wanted:checked.append(wanted['name']))
        # A deliberate exact-lock failure must survive as mismatch rather than ready.
        def reject(prefix,wanted):raise ValueError('installed archive identity differs from lock')
        source.package_record=reject
        with patch.dict('sys.modules',{'scenario_source_portable':source}),patch.dict(os.environ,{
                'CONDA_PREFIX':sys.prefix,'PIXI_PROJECT_MANIFEST':str(self.root/'transport/pixi.toml')}),patch.object(P.platform,'system',return_value='Linux'):
            output=io.StringIO()
            with contextlib.redirect_stdout(output):exec(P.TRANSPORT_PROBE,{})
        result=json.loads(output.getvalue())
        self.assertEqual(result['status'],'mismatch');self.assertIn('archive identity',result['detail'])

    def test_control_import_does_not_require_scientific_modules(self):
        code='''
import builtins
original=builtins.__import__
def stdlib_only(name,*args,**kwargs):
    if name.split('.')[0] in ('numpy','scipy','h5py','yaml'):
        raise ModuleNotFoundError('blocked test scientific import',name=name)
    return original(name,*args,**kwargs)
builtins.__import__=stdlib_only
import local_ui
print('Control imported without scientific modules')
'''
        prefix=[sys.executable]+(['--no-mpi','--disable-registry'] if Path(sys.executable).name.lower()=='pvpython.exe' else [])
        reply=subprocess.run(prefix+['-B','-c',code],cwd=Path(__file__).parent,capture_output=True,timeout=10)
        self.assertEqual(reply.returncode,0,reply.stderr.decode(errors='replace'))
        self.assertIn(b'without scientific modules',reply.stdout)


if __name__=='__main__':unittest.main()
