"""Portable metadata, mocked commands and synthetic raw fixtures; zero science."""
import copy
import hashlib
import importlib.util
from pathlib import Path
import unittest
import sys
import json
import os
import shutil
import tempfile
import types
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / 'transport'))
import scenario_source_portable as adapter
import scenario_workflow as W


class FiniteRequests(unittest.TestCase):
    def request(self, **changes):
        return {"detector": "AK02", "source_mode": adapter.CS137, "source_pose": "nominal", "primary_count": 20, "seed": 26092631, **changes}

    def test_eight_cs_tuples_with_selected_seed(self):
        for detector in adapter.DETECTORS:
            for count in (20, 500):
                with self.subTest(detector=detector, count=count):
                    value = self.request(detector=detector, primary_count=count, seed=26100342)
                    self.assertEqual(adapter.closed_request(value), value)

    def test_seed_edges(self):
        for seed in (1, 2147483646):
            adapter.closed_request(self.request(seed=seed))
        for seed in (0, 2147483647, -1, True, 1.0):
            with self.subTest(seed=seed), self.assertRaises(ValueError):
                adapter.closed_request(self.request(seed=seed))

    def test_closed_cs_count_and_pose(self):
        for changes in ({"primary_count": 10000}, {"primary_count": True}, {"source_pose": "plus5mm"}, {"detector": "GeRC02"}, {"cryostat": "other"}):
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                adapter.closed_request(self.request(**changes))

    def test_only_two_fixed_gamma_tuples(self):
        for detector in ("AK02", "SAP22"):
            adapter.closed_request(self.request(detector=detector, source_mode=adapter.GAMMA, source_pose="plus5mm"))
        for changes in ({"detector": "KMRC01_candidate"}, {"detector": "GeRC02_Li50min"}, {"source_pose": "nominal"}, {"primary_count": 500}, {"seed": 26100342}):
            value = self.request(**{"source_mode": adapter.GAMMA, "source_pose": "plus5mm", **changes})
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                adapter.closed_request(value)

    def test_original_signed_ring_and_seed_command(self):
        value = self.request(detector="KMRC01_candidate", primary_count=500, seed=26100342)
        self.assertEqual(adapter.model_id(value), "KMRC01_candidate")
        self.assertEqual(adapter.model_id(self.request(detector="GeRC02_Li50min")), "GeRC02")
        self.assertEqual(adapter.command(value), ["remage", "--flat-output", "-t", "1", "--rand-seed", "26100342", "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"])


class BuildAndBindingFixtures(unittest.TestCase):
    def setUp(self):
        self.identity = {"windows_root": "D:\\student\\clone", "linux_root": "/mnt/d/student/clone", "compiled_project_local": "/mnt/d/student/clone/.local"}
        self.runtime = {"kind": "fixture", "prefix": "/locked/prefix", "lock_sha256": adapter.PINNED["transport/pixi.lock"]}
        self.producer = "a" * 64
        self.recipe = {"configure_argv": ["cmake", "fixed-configure"], "build_argv": ["cmake", "fixed-target"], "cwd": "/mnt/d/student/clone", "generator": "Ninja", "target": "cryostat_export", "compiler": "/locked/prefix/bin/c++"}
        self.semantics = {"cache_identity": {"CMAKE_HOME_DIRECTORY": "/mnt/d/student/clone/transport"}, "compiler_identity": {"sha256": "b" * 64}, "linker_identity": {"sha256": "c" * 64}, "target_compile_argv": ["c++", "fixed"], "evidence_sha256": {"file": "d" * 64}}
        self.receipt = {"kind": "portable_source_exporter_build_v1", "schema_version": 1, "status": "complete", "adapter_version": 1,
                        "producer_sha256": self.producer, "project_identity": self.identity, "source_sha256": dict(adapter.PINNED), "runtime": self.runtime,
                        "build": {**self.recipe, **self.semantics, "configure_returncode": 0, "build_returncode": 0, "configure_wall_s": 0.5, "build_wall_s": 1.5},
                        "exporter": {"ref": adapter.EXPORTER_REF, "bytes": 91000, "sha256": "e" * 64}}

    def validate(self, receipt):
        return adapter.validate_build_receipt(receipt, self.identity, self.runtime, self.producer, self.recipe, self.semantics)

    def test_consistent_different_root_no_historical_binary_pin(self):
        self.validate(self.receipt)
        self.assertNotEqual(self.receipt["exporter"]["bytes"], 83872)
        self.assertNotEqual(self.receipt["exporter"]["sha256"], "87b510882ed3f07b610895fddc93d7c3a4d16e8cf2b5a22d2d7994b31164266e")

    def test_foreign_copied_root_is_refused(self):
        value = copy.deepcopy(self.receipt)
        value["project_identity"]["linux_root"] = "/mnt/c/old-owner/root"
        with self.assertRaises(ValueError):
            self.validate(value)

    def test_rehashed_canonical_source_and_lock_edits_refused(self):
        for ref in ("models/GeRC02.yaml", "models/KMRC01_candidate.yaml", "transport/scenario_prepare.py", "transport/pixi.lock"):
            value = copy.deepcopy(self.receipt)
            value["source_sha256"][ref] = "f" * 64
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                self.validate(value)

    def test_rehashed_recipe_and_target_overrides_refused(self):
        for key, replacement in (("configure_argv", ["cmake", "-DEXTRA=1"]), ("target", "foreign"), ("compiler", "/foreign/compiler"), ("target_compile_argv", ["c++", "-include", "injection.h"])):
            value = copy.deepcopy(self.receipt)
            value["build"][key] = replacement
            with self.subTest(key=key), self.assertRaises(ValueError):
                self.validate(value)

    def test_missing_partial_wrong_package_and_bool_exit_refused(self):
        modifications = [lambda v: v.pop("producer_sha256"), lambda v: v.update(status="failed"),
                         lambda v: v["runtime"].update(lock_sha256="0" * 64), lambda v: v["build"].update(build_returncode=False),
                         lambda v: v["exporter"].update(ref="../foreign"), lambda v: v["build"].update(build_wall_s=float("nan"))]
        for change in modifications:
            value = copy.deepcopy(self.receipt)
            change(value)
            with self.assertRaises(ValueError):
                self.validate(value)

    def test_marker_is_closed_and_maps_are_separate(self):
        marker = {"kind": adapter.EXECUTION_KIND, "version": 1, "source_mode": adapter.CS137, "adapter_ref": adapter.ADAPTER_REF,
                  "adapter_sha256": "a" * 64, "build_receipt_ref": adapter.BUILD_RECEIPT_REF, "build_receipt_sha256": "b" * 64,
                  "exporter_ref": adapter.EXPORTER_REF, "exporter_sha256": "c" * 64, "exporter_bytes": 91000}
        portable = {adapter.ADAPTER_REF: "a" * 64, adapter.BUILD_RECEIPT_REF: "b" * 64, adapter.EXPORTER_REF: "c" * 64}
        adapter.validate_execution_binding(marker, portable, marker, portable)
        for edits in ({"kind": "portable_gamma_execution_v1"}, {"source_mode": adapter.GAMMA}, {"version": True}, {"extra": 1}, {"exporter_sha256": "d" * 64}):
            with self.subTest(edits=edits), self.assertRaises(ValueError):
                adapter.validate_execution_binding({**marker, **edits}, portable, marker, portable)
        with self.assertRaises(ValueError):
            adapter.validate_execution_binding(marker, {**portable, "transport/ring_cs137.py": "f" * 64}, marker, portable)

    def test_build_receipt_source_and_runtime_changes_after_check(self):
        saved={'kind':'portable_source_checked_plan_v1','request':FiniteRequests().request(),
               'execution_contract':{'build_receipt_sha256':'a'*64,'exporter_sha256':'b'*64},
               'portable_source_sha256':{adapter.ADAPTER_REF:'c'*64},'runtime':{'executables':{'remage':{'sha256':'d'*64}}}}
        for change in (lambda v:v['execution_contract'].update(build_receipt_sha256='e'*64),
                       lambda v:v['execution_contract'].update(exporter_sha256='e'*64),
                       lambda v:v['portable_source_sha256'].update({adapter.ADAPTER_REF:'e'*64}),
                       lambda v:v['runtime']['executables']['remage'].update(sha256='e'*64)):
            actual=copy.deepcopy(saved);change(actual)
            with patch.object(adapter,'check',return_value=actual),self.assertRaisesRegex(ValueError,'checked plan changed'):
                adapter.validate_checked_plan(saved,saved['request'],'D:\\student\\clone')


class PathAndParameterFixtures(unittest.TestCase):
    def test_path_escape_and_drive_refs(self):
        for ref in ("../outside", "/root/file", "C:/outside", "a\\b", "a/../b", "./b", "a//b"):
            with self.subTest(ref=ref), self.assertRaises(ValueError):
                adapter.safe_ref(ref)

    def test_exact_eighteen_parameter_serializations(self):
        scenario = {"coordinate_transform": {"translation_global_mm": [0, 1.45, 0.29]}, "expected_vacuum_global_translation_mm": [0, 1.473, -3.71],
                    "spacer": {"vacuum_centre_mm": [0, -0.273, 4], "radius_mm": 13, "thickness_mm": 0.5},
                    "capsule": {"radius_mm": 3, "thickness_mm": 1, "wall_mm": 0.1}, "overlap_samples": 10000}
        gamma = adapter.parameter_text(scenario, [0, 42.073, 0.29], True)
        cs = adapter.parameter_text(scenario, [0, 37.073, 0.29], False)
        self.assertEqual(len(gamma.split()), 18)
        self.assertEqual(len(cs.split()), 18)
        self.assertEqual(cs, "0 1.45 0.29 0 1.473 -3.71 0 -0.273 4 13 0.5 0 37.073 0.29 3 1 0.1 10000\n")
        self.assertEqual(gamma, " ".join(format(v, ".17g") for v in [0, 1.45, 0.29, 0, 1.473, -3.71, 0, -0.273, 4, 13, 0.5, 0, 42.073, 0.29, 3, 1, 0.1, 10000]) + "\n")

    def test_one_shared_module_and_build_root(self):
        self.assertEqual(adapter.adapter_path(), HERE.parent / adapter.ADAPTER_REF)
        self.assertEqual(adapter.BUILD_REF, '.local/m2a/scenario-source-portable-build-v1')

    def test_actual_frozen_read_only_sources_match_admitted_pins(self):
        self.assertEqual(adapter.canonical_sources(), adapter.PINNED)

    def test_recorded_locked_package_tuples_and_metadata_mutations(self):
        packages=adapter.locked_packages()
        self.assertEqual([packages['remage'][k] for k in ('version','build','archive_sha256')],
                         ['1.1.0','py313h41e6809_0','a530e97339b28b71458939f74a7a434aaddd5414787042a5f5ed85f09c44638e'])
        base=adapter.ROOT/'.local/product-delivery-v1/m14a3-implementation/fixtures';base.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory(dir=base) as folder:
            prefix=Path(folder);metadata=prefix/'conda-meta';metadata.mkdir();wanted=packages['remage']
            path=metadata/'remage-fixture.json';value={k:wanted[k] for k in ('name','version','build','url')};value['sha256']=wanted['archive_sha256']
            path.write_text(adapter.text(value),encoding='utf-8');adapter.package_record(prefix,wanted)
            for key in ('version','build','url','sha256'):
                path.write_text(adapter.text({**value,key:'foreign'}),encoding='utf-8')
                with self.subTest(key=key),self.assertRaises(ValueError):adapter.package_record(prefix,wanted)
            path.write_text(adapter.text(value),encoding='utf-8');(metadata/'remage-other.json').write_text(adapter.text(value),encoding='utf-8')
            with self.assertRaisesRegex(ValueError,'ambiguous'):adapter.package_record(prefix,wanted)
        with patch.object(adapter,'runtime_snapshot',return_value={'runtime':'changed-executable'}),self.assertRaises(ValueError):
            adapter.recheck_runtime({'runtime':'checked-executable'})

    def test_rehashed_extra_target_link_option_or_shell_action_refused(self):
        runtime={'prefix':'/locked/prefix'};recipe={'compiler':'/locked/prefix/bin/c++'}
        compile='/locked/prefix/bin/c++ -c /mock/root/transport/cryostat_export.cc -o CMakeFiles/cryostat_export.dir/cryostat_export.cc.o'
        link=': && /locked/prefix/bin/c++ -O3 -DNDEBUG CMakeFiles/cryostat_export.dir/cryostat_export.cc.o -o cryostat_export -Wl,-rpath,/locked/prefix/lib /locked/prefix/lib/libG4gdml.so && :'
        adapter.validate_link_command(compile+'\n'+link,recipe,runtime)
        for changed in (link.replace('-O3','-O3 -s'),link.replace('libG4gdml.so','libG4gdml.so -Wl,--script,foreign.ld'),
                        link.replace('/locked/prefix/lib/libG4gdml.so','/foreign/lib/libG4gdml.so'),
                        link+' && echo changed'):
            with self.subTest(link=changed),self.assertRaises(ValueError):adapter.validate_link_command(compile+'\n'+changed,recipe,runtime)

    def test_rehashed_cmake_standard_libraries_override_refused(self):
        runtime={'prefix':'/locked/prefix','executables':{'ninja':{'ref':'bin/ninja'}}};recipe={'compiler':'/locked/prefix/bin/c++'}
        fields={'CMAKE_HOME_DIRECTORY':str(adapter.ROOT/'transport'),'CMAKE_CACHEFILE_DIR':str(adapter.ROOT/adapter.BUILD_REF),
                'CMAKE_GENERATOR':'Ninja','CMAKE_BUILD_TYPE':'Release','CMAKE_CXX_COMPILER':recipe['compiler'],
                'CMAKE_MAKE_PROGRAM':'/locked/prefix/bin/ninja','CMAKE_EXPORT_COMPILE_COMMANDS':'ON',
                'CMAKE_PROJECT_NAME':'m2a_geometry_probe','Geant4_DIR':'/locked/prefix/lib/cmake/Geant4',
                **adapter.build_flags(runtime['prefix']),'CMAKE_CXX_STANDARD_LIBRARIES':'-Wl,--script,foreign.ld'}
        with patch.object(adapter,'cache_fields',return_value=fields),self.assertRaisesRegex(ValueError,'CMAKE_CXX_STANDARD_LIBRARIES'):
            adapter.build_semantics(recipe,runtime)


class BuildRunner(unittest.TestCase):
    def test_closed_conda_activation_hints(self):
        prefix='/locked/prefix'
        hints=' '.join('-DCMAKE_'+key+'='+prefix+'/bin/x86_64-conda-linux-gnu-'+value
                       for key,value in (('AR','ar'),('CXX_COMPILER_AR','gcc-ar'),('C_COMPILER_AR','gcc-ar'),
                                         ('RANLIB','ranlib'),('CXX_COMPILER_RANLIB','gcc-ranlib'),
                                         ('C_COMPILER_RANLIB','gcc-ranlib'),('LINKER','ld'),('STRIP','strip')))
        hints+=' -DCMAKE_BUILD_TYPE=Release'
        with patch.dict(os.environ,{'CMAKE_ARGS':hints,'CMAKE_PREFIX_PATH':prefix+':'+prefix+'/x86_64-conda-linux-gnu/sysroot/usr'}):
            adapter.check_build_environment({'prefix':prefix})
            for changed in (hints+' -DEXTRA=1',hints.replace('Release','Debug'),
                            hints.replace(prefix+'/bin/', '/foreign/bin/',1),hints+' -DCMAKE_BUILD_TYPE=Release'):
                with patch.dict(os.environ,{'CMAKE_ARGS':changed}),self.assertRaises(ValueError):
                    adapter.check_build_environment({'prefix':prefix})
            with patch.dict(os.environ,{'CMAKE_PREFIX_PATH':prefix+':/foreign'}),self.assertRaises(ValueError):
                adapter.check_build_environment({'prefix':prefix})

    def setUp(self):
        base=adapter.ROOT/'.local/product-delivery-v1/m14a3-implementation/fixtures';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.root=Path(self.temp.name)/'alternate-clone';self.root.mkdir()
        self.h=adapter.helpers()[0]
        for ref in (*adapter.PINNED,adapter.ADAPTER_REF):
            target=self.root/ref;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(adapter.ROOT/ref,target)
        self.identity={'windows_root':str(self.root),'linux_root':str(self.root),'compiled_project_local':str(self.root/'.local')}
        self.runtime={'kind':'synthetic-build-runtime','prefix':str(self.root/'locked-prefix'),'executables':{'ninja':{'ref':'bin/ninja'}}}
        self.recipe={'configure_argv':['fixture-cmake','configure'],'build_argv':['fixture-cmake','build'],'cwd':str(self.root),'generator':'Ninja','target':'cryostat_export','compiler':'fixture-c++'}
        self.semantics={'cache_identity':{'CMAKE_HOME_DIRECTORY':str(self.root/'transport')},'compiler_identity':{'sha256':'a'*64},'linker_identity':{'sha256':'b'*64},'target_compile_argv':['fixture-c++'], 'evidence_sha256':{}}
        original_recheck=adapter.recheck_map
        def recheck(values,root=None):return original_recheck(values,self.root if root is None else root)
        def semantics(*args):
            value=copy.deepcopy(self.semantics)
            value['evidence_sha256']={adapter.BUILD_REF+'/'+ref:adapter.digest(self.root/adapter.BUILD_REF/ref) for ref in ('configure.log','build.log','target-commands.txt')}
            return value
        for obj,name,value in ((adapter,'ROOT',self.root),(adapter,'adapter_path',lambda:self.root/adapter.ADAPTER_REF),
                               (adapter,'project_identity',lambda w:copy.deepcopy(self.identity)),(adapter,'runtime_snapshot',lambda:copy.deepcopy(self.runtime)),
                               (adapter,'build_recipe',lambda r:copy.deepcopy(self.recipe)),(adapter,'build_semantics',semantics),(adapter,'recheck_map',recheck),
                               (adapter,'helpers',lambda:(self.h,None,None,None,None,None))):
            p=patch.object(obj,name,value);p.start();self.addCleanup(p.stop)
        env=patch.dict(os.environ,{v:'' for v in ('CMAKE_ARGS','CMAKE_GENERATOR','CMAKE_TOOLCHAIN_FILE','CMAKE_PROJECT_INCLUDE','CMAKE_PROJECT_INCLUDE_BEFORE','CMAKE_PREFIX_PATH')});env.start();self.addCleanup(env.stop)

    def runner(self,argv,**kwargs):
        kwargs['stdout'].write('Synthetic fixed-build command fixture; no compiler executed.\n')
        if argv==self.recipe['build_argv']:(self.root/adapter.EXPORTER_REF).write_bytes(b'SYNTHETIC-EXPORTER-NOT-EXECUTABLE')
        return types.SimpleNamespace(returncode=0)

    def test_fixed_mock_build_and_idempotent_matching_receipt(self):
        with patch.object(adapter.subprocess,'run',side_effect=self.runner) as mocked:
            first=adapter.build_exporter(self.identity['windows_root']);self.assertEqual(mocked.call_count,3)
            second=adapter.build_exporter(self.identity['windows_root']);self.assertEqual(mocked.call_count,3)
        self.assertEqual(first,second);self.assertEqual(first['status'],'complete')
        self.assertEqual(adapter.load(self.root/adapter.BUILD_REF/'build-attempt.json')['status'],'complete')
        self.assertTrue(adapter.file_readiness(self.root)['available'])
        foreign=adapter.load(self.root/adapter.BUILD_RECEIPT_REF);foreign['project_identity']['windows_root']='D:\\copied-owner-root'
        (self.root/adapter.BUILD_RECEIPT_REF).write_text(adapter.text(foreign),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'foreign Windows'):adapter.file_readiness(self.root)
        (self.root/adapter.BUILD_RECEIPT_REF).write_text(adapter.text(first),encoding='utf-8')
        (self.root/adapter.EXPORTER_REF).write_bytes(b'REHASHED-OTHER-EXPORTER')
        receipt=adapter.load(self.root/adapter.BUILD_RECEIPT_REF)
        receipt['exporter'].update(bytes=(self.root/adapter.EXPORTER_REF).stat().st_size,sha256=adapter.digest(self.root/adapter.EXPORTER_REF))
        (self.root/adapter.BUILD_RECEIPT_REF).write_text(adapter.text(receipt),encoding='utf-8')
        # A post-Check receipt rehash changes the plan binding even when all
        # local binary claims are forged consistently; receipts are not signatures.
        self.assertNotEqual(adapter.digest(self.root/adapter.BUILD_RECEIPT_REF),hashlib.sha256(adapter.text(first).encode()).hexdigest())

    def test_source_change_during_mock_build_keeps_failed_attempt(self):
        def changing(argv,**kwargs):
            result=self.runner(argv,**kwargs)
            if argv==self.recipe['configure_argv']:(self.root/'transport/CMakeLists.txt').write_text('CHANGED FIXTURE SOURCE',encoding='utf-8')
            return result
        with patch.object(adapter.subprocess,'run',side_effect=changing),self.assertRaisesRegex(ValueError,'changed source'):
            adapter.build_exporter(self.identity['windows_root'])
        self.assertEqual(adapter.load(self.root/adapter.BUILD_REF/'build-attempt.json')['status'],'failed')
        self.assertFalse((self.root/adapter.BUILD_RECEIPT_REF).exists())

    def test_incomplete_or_foreign_build_refused_without_commands(self):
        (self.root/adapter.BUILD_REF).mkdir(parents=True)
        with patch.object(adapter.subprocess,'run',side_effect=AssertionError('Incomplete build was rebuilt')),self.assertRaises(OSError):
            adapter.build_exporter(self.identity['windows_root'])
        with patch.dict(os.environ,{'CMAKE_ARGS':'-DEXTRA=1'}),self.assertRaisesRegex(ValueError,'override'):
            adapter.build_exporter(self.identity['windows_root'])


class PairedPreparation(unittest.TestCase):
    def setUp(self):
        self.base=adapter.ROOT/'.local/product-delivery-v1/m14a3-implementation/fixtures'
        self.base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=self.base);self.addCleanup(self.temp.cleanup)
        self.directory=Path(self.temp.name)/'prepared'
        self.request={'detector':'AK02','source_mode':adapter.GAMMA,'source_pose':'plus5mm','primary_count':20,'seed':26092631}
        self.h,self.cs,self.s,self.gamma,self.ring,self.models=adapter.helpers()
        self.checked={'request':self.request,'execution_contract':{'kind':adapter.EXECUTION_KIND,'version':1,'source_mode':adapter.GAMMA,
                      'exporter_sha256':'f'*64},'portable_source_sha256':{adapter.ADAPTER_REF:adapter.digest(adapter.adapter_path())},
                      'runtime':{'kind':'synthetic-no-runtime'},'upstream_sha256':self.cs.upstream_hashes(),
                      'gamma_plan':self.s.check(adapter.ROOT/'scenarios/m11a-ak02-mono_gamma_662_axis_v1-plus5mm.json')}
        for target,name,value in ((adapter,'validate_checked_plan',lambda *a:copy.deepcopy(self.checked)),
                                  (adapter,'recheck_runtime_data',lambda *a:0),
                                  (self.s,'frozen_inventory',lambda *a:{'transport/scenario_prepare.py':adapter.PINNED['transport/scenario_prepare.py']})):
            mocked=patch.object(target,name,side_effect=value);mocked.start();self.addCleanup(mocked.stop)
        def datasets(output,runtime,mode):
            path=output/'runtime';path.mkdir()
            self.h.publish_json(path/'emlow-data.json',{'kind':'synthetic-fixture'})
            self.h.publish_json(path/'runtime.json',{'identity':runtime})
        mocked=patch.object(adapter,'runtime_data',side_effect=datasets);mocked.start();self.addCleanup(mocked.stop)
        import test_scenario_prepare as fixture
        self.report=fixture.report_fixture(self.checked['gamma_plan'])
        def exporter(command,**kwargs):
            Path(command[-2]).write_text('<gdml><!-- SYNTHETIC UNIT FIXTURE --></gdml>\n',encoding='utf-8')
            Path(command[-1]).write_text(adapter.text(self.report),encoding='utf-8')
            kwargs['stdout'].write('Synthetic command fixture; native exporter never ran.\n')
            return types.SimpleNamespace(returncode=0)
        with patch.object(adapter.subprocess,'run',side_effect=exporter) as dispatch:
            adapter.prepare(self.request,self.directory,'D:\\mock\\clone',self.checked)
            self.assertEqual(dispatch.call_count,1)

    def rehash(self):
        meta=adapter.load(self.directory/'prepared.json')
        meta['files_sha256']=adapter.file_inventory(self.directory)
        for ref in ('prepared.json','prepare-receipt.json'):meta['files_sha256'].pop(ref,None)
        (self.directory/'prepared.json').write_text(adapter.text(meta),encoding='utf-8')
        receipt=adapter.load(self.directory/'prepare-receipt.json');receipt['prepared_sha256']=adapter.digest(self.directory/'prepared.json')
        (self.directory/'prepare-receipt.json').write_text(adapter.text(receipt),encoding='utf-8')

    def test_complete_reader_and_output_collision(self):
        result=adapter.read_prepared(self.directory,'D:\\mock\\clone')
        self.assertEqual(result[1]['instance']['primary_count'],20)
        with self.assertRaisesRegex(ValueError,'output collision'):
            adapter.prepare(self.request,self.directory,'D:\\mock\\clone',self.checked)

    def test_rehashed_macro_parameters_probe_and_contour_refused(self):
        for ref in ('run.mac','parameters.txt','probe-points.txt','canonical.gdml'):
            path=self.directory/ref;original=path.read_bytes()
            path.write_bytes(original+b'\nchanged\n');self.rehash()
            with self.subTest(ref=ref),self.assertRaises(ValueError):adapter.read_prepared(self.directory,'D:\\mock\\clone')
            path.write_bytes(original);self.rehash()

    def test_rehashed_material_pose_count_seed_and_marker_refused(self):
        for target,mutate in (('geometry-report.json',lambda v:v['volumes'][16].update(material='G4_AIR')),
                              ('geometry-report.json',lambda v:v['volumes'][19]['translation_global_mm'].__setitem__(1,37.073)),
                              ('resolved-instance.json',lambda v:v['instance'].update(primary_count=500)),
                              ('resolved-instance.json',lambda v:v['instance'].update(seed=1)),
                              ('prepared.json',lambda v:v['execution_contract'].update(kind='legacy')),
                              ('prepared.json',lambda v:v['source_sha256'].update({'transport/scenario_prepare.py':'0'*64}))):
            path=self.directory/target;original=path.read_bytes();data=adapter.load(path);mutate(data)
            path.write_text(adapter.text(data),encoding='utf-8');self.rehash()
            with self.subTest(target=target),self.assertRaises(ValueError):adapter.read_prepared(self.directory,'D:\\mock\\clone')
            path.write_bytes(original);self.rehash()

    def test_receipt_command_returncode_or_status_refused(self):
        path=self.directory/'prepare-receipt.json';original=path.read_bytes()
        for edits in ({'status':'failed'},{'returncode':False},{'command':['arbitrary-binary']}):
            value=adapter.load(path);value.update(edits);path.write_text(adapter.text(value),encoding='utf-8')
            with self.subTest(edits=edits),self.assertRaises(ValueError):adapter.read_prepared(self.directory,'D:\\mock\\clone')
            path.write_bytes(original)


class RawAndStream(unittest.TestCase):
    def setUp(self):
        base=adapter.ROOT/'.local/product-delivery-v1/m14a3-implementation/fixtures';base.mkdir(parents=True,exist_ok=True)
        self.temp=tempfile.TemporaryDirectory(dir=base);self.addCleanup(self.temp.cleanup);self.directory=Path(self.temp.name)
        self.directory.joinpath('stream').mkdir()
        self.h,self.cs,self.s,self.gamma,*_=adapter.helpers()

    def fixture(self,gamma=True):
        path=self.directory/'truth.lh5'
        if gamma:
            import test_scenario_transport as fixture
            plan=self.s.check(adapter.ROOT/'scenarios/m11a-ak02-mono_gamma_662_axis_v1-plus5mm.json')
            _,points=self.h.load_model('AK02')
            self.meta={'source_position_global_mm':plan['source_position_global_mm'],'coordinate_transform':plan['coordinate_transform'],
                       'contour_rz_mm':points,'material_tables':{'stp/'+e[0]:e[3] for e in self.s.LEDGER if e[0]!='ledger_0_PV'}}
            fixture.raw_fixture(path,self.meta);self.mode=adapter.GAMMA
            self.events=list(self.gamma.iter_events(path,self.meta));self.name='events-00000000.jsonl';first='first_initial_primary_id'
        else:
            import test_cs137 as fixture
            self.meta=fixture.fixture(path,count=20);self.mode=adapter.CS137
            self.events=list(self.cs.iter_decays(path,self.meta));self.name='decays-00000000.jsonl';first='first_global_decay_id'
        self.request={'source_mode':self.mode,'primary_count':20}
        self.chunks=[{'file':self.name,'count':20,first:0}];self.save(self.events)

    def save(self,events):
        path=self.directory/'stream'/self.name
        path.write_text(''.join(json.dumps(e,sort_keys=True,separators=(',',':'),allow_nan=False)+'\n' for e in events),encoding='utf-8')
        self.chunks[0]['sha256']=adapter.digest(path)

    def test_full_gamma_raw_comparison_and_rehashed_events(self):
        self.fixture();self.assertEqual(adapter.validate_stream_events(self.directory,self.meta,self.request,self.chunks),20)
        for mutate in (lambda e:e.pop(),lambda e:e[3].update(zero_ge=False),
                       lambda e:e[0]['steps'][0].update(raw_row_index=9),
                       lambda e:e[0]['steps'][0].update(time_ns=5),
                       lambda e:e[0]['tracks'][1].update(parent_trackid=99)):
            changed=copy.deepcopy(self.events);mutate(changed);self.save(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):adapter.validate_stream_events(self.directory,self.meta,self.request,self.chunks)

    def test_delayed_cs_groups_zero_ids_raw_rows_rehashed(self):
        self.fixture(False);self.assertEqual(adapter.validate_stream_events(self.directory,self.meta,self.request,self.chunks),20)
        self.assertEqual(len(self.events[0]['pulse_groups']),2)
        for mutate in (lambda e:e[1].update(global_decay_id=0),lambda e:e.pop(1),
                       lambda e:e[0]['pulse_groups'][1]['relative_times_ns'].__setitem__(0,1),
                       lambda e:e[0]['pulse_groups'][0]['row_indices'].__setitem__(0,2),
                       lambda e:e[0]['steps'][2].update(time_ns=0)):
            changed=copy.deepcopy(self.events);mutate(changed);self.save(changed)
            with self.subTest(mutate=mutate),self.assertRaises(ValueError):adapter.validate_stream_events(self.directory,self.meta,self.request,self.chunks)

    def test_raw_units_ancestry_and_uid_edits_refused(self):
        self.fixture();import h5py
        for mutate,restore in ((lambda r:r['stp/germanium/edep'].attrs.__setitem__('units','MeV'),lambda r:r['stp/germanium/edep'].attrs.__setitem__('units','keV')),
                               (lambda r:r['tracks/parent_trackid'].__setitem__(1,99),lambda r:r['tracks/parent_trackid'].__setitem__(1,1))):
            with h5py.File(self.directory/'truth.lh5','r+') as raw:mutate(raw)
            with self.assertRaises(ValueError):adapter.validate_stream_events(self.directory,self.meta,self.request,self.chunks)
            with h5py.File(self.directory/'truth.lh5','r+') as raw:restore(raw)
        with h5py.File(self.directory/'truth.lh5','r+') as raw:
            aliases=raw['stp/__by_uid__'];key=next(iter(aliases));del aliases[key];aliases[key]=h5py.SoftLink('/tracks')
        with self.assertRaises(ValueError):adapter.raw_metadata(self.directory/'truth.lh5',self.meta,self.request)


class WorkflowIntegration(unittest.TestCase):
    def setUp(self):
        self.config={'name':'portable-fixture','detector':'SAP22','cryostat':W.CRYOSTAT,'source':W.GAMMA,'pose':'plus5mm',
                     'seed':26092631,'primary_count':20,'threads':1,'electronics':W.catalog()['electronics_defaults']}
        self.portable={'kind':'portable_source_checked_plan_v1','schema_version':1,'request':W.portable_request(self.config),
                       'execution_contract':{'kind':adapter.EXECUTION_KIND},'portable_source_sha256':{adapter.ADAPTER_REF:'a'*64},'runtime':{'kind':'fixture'}}
    def plan(self):
        return W.check(self.config,validate_settings=lambda e,r:{'profile':{},'configuration':dict(e,max_window_ns=1000000,max_samples_per_event=500000),'physics_sha256':'b'*64},
                       pin_reader=lambda d,r:{'fixture':'c'*64},runtime_reader=lambda t:{'julia_sha256':'d'*64},portable_reader=lambda c,r:copy.deepcopy(self.portable))

    def test_portable_dispatch_and_canonical_windows_root_data(self):
        plan=self.plan();cmds=W.stage_commands(W.run_path(self.config['name']),plan['resolved'],environment={'JULIA_EXE':'fixture-julia'})
        for stage in ('geometry','radiation','event_ledger'):
            self.assertIn('./scenario_source_portable.py',cmds[stage]);self.assertIn('--windows-root',cmds[stage]);self.assertIn(str(W.ROOT),cmds[stage])
            self.assertIn('./workflow.sh',cmds[stage]);self.assertNotIn('--exporter',cmds[stage])
        self.assertIn('ICPC',next(d['label'] for d in W.catalog()['detectors'] if d['id']=='SAP22'))

    def test_check_does_not_build_and_current_source_runtime_changes_refused(self):
        plan=self.plan()
        for section in ('portable_source_sha256','runtime'):
            altered=copy.deepcopy(plan);altered['resolved']['portable_source_plan'][section]['mutant']='rehash';altered['configuration_sha256']=W.digest(altered['resolved'])
            with patch.object(W,'check',return_value=plan),self.assertRaises(W.ControlError):W.admit(altered)
        observed=[]
        def command(argv,**kwargs):
            observed.append(argv);return types.SimpleNamespace(returncode=0,stdout=W.encoded(self.portable),stderr=b'')
        result=W.portable_query(['check','--request-json','{}'],runner=command)
        self.assertEqual(result,self.portable);self.assertNotIn('build-exporter',observed[0]);self.assertNotIn('install',' '.join(observed[0]))
        self.assertIn('--exec',observed[0])
        self.assertIn('--locked --no-install',(W.ROOT/'transport/workflow.sh').read_text(encoding='utf-8'))

    def test_post_extraction_radiation_check_uses_full_ledger_reader(self):
        plan=self.plan()['resolved']
        with tempfile.TemporaryDirectory(dir=W.ROOT/'.local/product-delivery-v1/m14a3-implementation/fixtures') as tmp:
            directory=Path(tmp)
            with patch.object(W,'run_path',return_value=directory),patch.object(W,'portable_query',return_value=self.portable) as query:
                W.portable_stage(directory,plan,'radiation')
                self.assertEqual(query.call_args.args[0][-1],'radiation')
                (directory/'transport/stream').mkdir(parents=True)
                (directory/'transport/stream/manifest.json').write_text('{}',encoding='utf-8')
                W.portable_stage(directory,plan,'radiation')
                self.assertEqual(query.call_args.args[0][-1],'event_ledger')
                W.portable_stage(directory,plan,'event_ledger')
                self.assertEqual(query.call_args.args[0][-1],'event_ledger')
                with patch.object(W,'portable_query',side_effect=ValueError('Invalid complete ledger')),self.assertRaises(ValueError):
                    W.portable_stage(directory,plan,'radiation')

    def test_process_inventory_matches_adapter_build_and_descendants(self):
        import workflow_inspection as I
        for command in ('python scenario_source_portable.py run','cmake --build .local/m2a/scenario-source-portable-build-v1',
                        'ninja cryostat_export','x86_64-conda-linux-gnu-g++ -o cryostat_export','cc1plus source.cc','wsl.exe bash workflow.sh'):
            self.assertIsNotNone(I.SCIENCE.search(command))
        for compiler in ('g++','gcc','cc1plus','collect2','ld'):
            for command in (compiler+' source.o','x86_64-conda-linux-gnu-'+compiler+' source.o',compiler+'.exe source.o'):
                self.assertIsNotNone(I.SCIENCE.search(command))
        for command in ('viewer --field value','viewer --child task','viewer --world value'):
            self.assertIsNone(I.SCIENCE.search(command))

    def test_windows_setup_switch_is_explicit_and_never_uses_install(self):
        launcher=(W.ROOT/'tools/scenario_cli.ps1').read_text(encoding='utf-8')
        self.assertIn('[switch]$BuildPortableSourceExporter',launcher)
        builder=launcher.split('function Build-PortableSourceExporter {',1)[1].split('function Require-Ready',1)[0]
        self.assertIn('./workflow.sh python -B ./scenario_source_portable.py build-exporter --windows-root $root',builder)
        self.assertNotIn('pixi install',builder)
        self.assertIn("if($BuildPortableSourceExporter){Build-PortableSourceExporter;exit 0}",launcher)


if __name__ == '__main__':unittest.main()
