"""Build/check the additive catalog exporter in the existing locked transport runtime."""
from __future__ import annotations
import argparse,copy,json,shlex,subprocess,time
from pathlib import Path
import handoff as h
import scenario_source_portable as P
BUILD_REF='.local/m2a/catalog-source-build-v1'
RECEIPT_REF=BUILD_REF+'/exporter-build.json'
EXPORTER_REF=BUILD_REF+'/cryostat_catalog_export'
SOURCE_REFS=('transport/catalog_exporter_setup.py','transport/catalog_exporter/CMakeLists.txt','transport/cryostat_catalog_export.cc','transport/cryostat_export.cc')

def authority(windows_root=None):
    old=P.read_build_receipt(windows_root)
    recipe=copy.deepcopy(old['build']);configure=recipe['configure_argv']
    configure[configure.index('-S')+1]=str(h.ROOT/'transport/catalog_exporter')
    configure[configure.index('-B')+1]=str(h.ROOT/BUILD_REF)
    build=recipe['build_argv'];build[build.index('--build')+1]=str(h.ROOT/BUILD_REF);build[build.index('--target')+1]='cryostat_catalog_export'
    return old,{'configure_argv':configure,'build_argv':build,'cwd':str(h.ROOT),'target':'cryostat_catalog_export'}, {ref:h.sha256(h.ROOT/ref) for ref in SOURCE_REFS}

def read(windows_root=None):
    old,recipe,sources=authority(windows_root);r=csload(h.ROOT/RECEIPT_REF)
    h.require(r['kind']=='catalog_exporter_build_v1' and r['status']=='complete' and r['source_sha256']==sources and r['runtime']==old['runtime'] and r['legacy_build_sha256']==h.sha256(h.ROOT/P.BUILD_RECEIPT_REF),'Catalog exporter source/runtime authority changed')
    h.require(r['recipe']==recipe and r['exporter']['ref']==EXPORTER_REF and r['exporter']['sha256']==h.sha256(h.ROOT/EXPORTER_REF) and r['exporter']['bytes']==(h.ROOT/EXPORTER_REF).stat().st_size,'Catalog exporter recipe/binary changed')
    for ref,digest in r['evidence_sha256'].items():h.require(h.sha256(h.ROOT/ref)==digest,'Catalog build evidence changed')
    cache=P.cache_fields(h.ROOT/BUILD_REF/'CMakeCache.txt');base=old['build']['cache_identity']
    for key in ('CMAKE_CXX_COMPILER','CMAKE_CXX_FLAGS','CMAKE_CXX_FLAGS_RELEASE','CMAKE_EXE_LINKER_FLAGS','CMAKE_EXE_LINKER_FLAGS_RELEASE','Geant4_DIR','CMAKE_GENERATOR','CMAKE_MAKE_PROGRAM'):
        h.require(cache[key]==base[key],'Catalog compiler/locked flags changed: '+key)
    h.require(cache['CMAKE_HOME_DIRECTORY']==str(h.ROOT/'transport/catalog_exporter') and cache['CMAKE_CACHEFILE_DIR']==str(h.ROOT/BUILD_REF) and cache['CMAKE_PROJECT_NAME']=='catalog_geometry_export','Catalog build root/target changed')
    commands=csload(h.ROOT/BUILD_REF/'compile_commands.json');h.require(len(commands)==1 and commands[0]['file']==str(h.ROOT/'transport/cryostat_catalog_export.cc') and commands[0]['directory']==str(h.ROOT/BUILD_REF),'Catalog compile source/root changed')
    return r

def csload(path):return json.loads(Path(path).read_text(encoding='utf-8'))

def build(windows_root=None):
    if (h.ROOT/RECEIPT_REF).is_file():return read(windows_root)
    old,recipe,sources=authority(windows_root);d=h.ROOT/BUILD_REF;h.require(not d.exists(),'Failed/partial catalog build is retained; inspect it before another build')
    d.mkdir(parents=True);r={'kind':'catalog_exporter_build_v1','status':'failed','source_sha256':sources,'runtime':old['runtime'],'legacy_build_sha256':h.sha256(h.ROOT/P.BUILD_RECEIPT_REF),'recipe':recipe};started=time.perf_counter()
    try:
        for stage in ('configure','build'):
            t=time.perf_counter()
            with (d/(stage+'.log')).open('x',encoding='utf-8') as log:
                p=subprocess.run(recipe[stage+'_argv'],cwd=h.ROOT,stdout=log,stderr=subprocess.STDOUT,check=False)
            r[stage+'_returncode']=p.returncode;r[stage+'_wall_s']=time.perf_counter()-t;h.require(p.returncode==0,'Catalog '+stage+' failed; preserve log')
        h.require(sources=={ref:h.sha256(h.ROOT/ref) for ref in SOURCE_REFS},'Catalog exporter source changed during build')
        r['exporter']={'ref':EXPORTER_REF,'sha256':h.sha256(h.ROOT/EXPORTER_REF),'bytes':(h.ROOT/EXPORTER_REF).stat().st_size}
        compiler_files=list(d.glob('CMakeFiles/*/CMakeCXXCompiler.cmake'));h.require(len(compiler_files)==1,'Ambiguous catalog compiler evidence')
        names=['configure.log','build.log','CMakeCache.txt','compile_commands.json','build.ninja','CMakeFiles/rules.ninja',compiler_files[0].relative_to(d).as_posix()]
        r['evidence_sha256']={BUILD_REF+'/'+ref:h.sha256(d/ref) for ref in names};r['status']='complete'
    except BaseException as error:r['error']=str(error);raise
    finally:r['total_wall_s']=time.perf_counter()-started;h.publish_json(h.ROOT/RECEIPT_REF,r)
    return read(windows_root)

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('build','check'));p.add_argument('--windows-root');a=p.parse_args()
    print(json.dumps(build(a.windows_root) if a.action=='build' else read(a.windows_root),sort_keys=True))
if __name__=='__main__':main()
