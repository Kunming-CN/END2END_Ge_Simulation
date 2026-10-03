"""Finite source orchestration with an explicit clone-local exporter build.

One orchestration layer delegates geometry and raw-event algorithms to
unchanged historical helpers. Local receipts detect change; they do not provide
cryptographic authentication against forged binaries plus forged local evidence.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import math
import os
from pathlib import Path
import platform
import re
import shlex
import shutil
import subprocess
import sys
import time

VERSION = 1
EXECUTION_KIND = "portable_source_execution_v1"
ADAPTER_REF = "transport/scenario_source_portable.py"
BUILD_REF = ".local/m2a/scenario-source-portable-build-v1"
BUILD_RECEIPT_REF = BUILD_REF + "/exporter-build.json"
EXPORTER_REF = BUILD_REF + "/cryostat_export"
DETECTORS = ("AK02", "SAP22", "GeRC02_Li50min", "KMRC01_candidate")
CS137 = "cs137_point_decay_v1"
GAMMA = "mono_gamma_662_axis_v1"
PREP_FILES = {"canonical.gdml", "probe-points.txt", "parameters.txt",
              "geometry.gdml", "geometry-report.json", "geometry.log", "run.mac"}
DIAGNOSTIC = r"COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read|cryostat_export:"
PINNED = {
    "transport/ring_cs137.py": "fa9725cff1e31c51f148b453c8239b8e7a8f62247e7a9e65847fa568d99ac34f",
    "transport/cs137.py": "de1c276a304dad5ffa1338732e96719b22ad115e4dd8344d04ae5a91c934224d",
    "transport/handoff.py": "5eaf9c41852b4f4b45b3c36f78314b9fba28c39fcc4155694e8b6459375df193",
    "transport/scenario_prepare.py": "4dd27621d0b91f53552428c5238d219459feff72cdcdd26609bc140460f9906c",
    "transport/scenario_transport.py": "a417048e496cb5f0aee4ecac755404cee80cc8b38d2235f3b4b305ae62eae6ac",
    "tools/ring_model_contract.py": "5a8a896e5755a73a6039dec04037bec9259f43b1934d2d167a018562f88ab8d2",
    "transport/CMakeLists.txt": "9ea59c94d38667c65a61644164ddc245f012996a9833efc830fb82aa717f8ab1",
    "transport/cryostat_export.cc": "af44c9893e4576151511b185989ff1bc88431b36261d2d3b2607640d335e767b",
    "transport/geometry_probe.cc": "74b6afef5854e446dfbfa79acc9e79e910c2707e02bda69da8177c30eee81977",
    "transport/pixi.toml": "87991463283a4f00b7e8a2758d9019c39ebe0fcad1387e87e500ed500f0638dd",
    "transport/pixi.lock": "c212a7f7e78bb7af4687bbbc7322659975961e62c3ea71a6f325e65e554b56be",
    "transport/cryostat_nominal.json": "9cad951c14213ac64d1e0c83c6ee44e7f4b9990d80979fd5bae35797daaf0edb",
    "transport/cryostat-source.json": "5967d5d0f8500a40f704bf653be2dc1a0f69e77239f643a8f7140533c9201e2a",
    "models/catalog.json": "ac5edd4c976a37cfcc80a8e507ac9347246a942ac843ed2ecc683079f220653b",
    "models/AK02.yaml": "793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
    "models/SAP22.yaml": "614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3",
    "models/GeRC02.yaml": "7a655caeb660c07df8fcd9af51cc0998daea15f16e31f9c6afcacb89daf39218",
    "models/KMRC01_candidate.yaml": "d4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6",
    "models/ADLChargeDriftModel/drift_velocity_config.yaml": "642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6",
    "simulation/native_readout_profile.json": "7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6",
}
PACKAGE_NAMES = ("python", "numpy", "h5py", "pyyaml", "remage", "geant4", "geant4-data-emlow",
                 "geant4-data-ensdfstate", "geant4-data-photonevaporation",
                 "geant4-data-radioactivedecay", "cmake", "ninja",
                 "gcc_linux-64", "gxx_linux-64", "gcc_impl_linux-64",
                 "gxx_impl_linux-64", "binutils_impl_linux-64")
BUILD_KEYS = {"kind", "schema_version", "status", "adapter_version", "producer_sha256",
              "project_identity", "source_sha256", "runtime", "build", "exporter"}


def require(ok, message):
    if not ok:
        raise ValueError(message)


def text(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def exact(actual, expected, message):
    require(text(actual) == text(expected), message)


def digest(path):
    out = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            out.update(block)
    return out.hexdigest()


def json_pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def bad_constant(value):
    raise ValueError("nonfinite JSON constant: " + value)


def finite_float(value):
    parsed = float(value)
    require(math.isfinite(parsed), "nonfinite JSON number")
    return parsed


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=json_pairs, parse_constant=bad_constant, parse_float=finite_float)


def root_from_module():
    for parent in Path(__file__).resolve().parents:
        if (parent / "transport/CMakeLists.txt").is_file() and (parent / "models/catalog.json").is_file():
            return parent
    raise ValueError("project root cannot be derived from adapter location")


ROOT = root_from_module()


def safe_ref(ref):
    require(type(ref) is str and ref and "\\" not in ref and not Path(ref).is_absolute()
            and all(part not in ("", ".", "..") for part in ref.split("/")), "unsafe project reference")
    require(not re.match(r"^[A-Za-z]:", ref), "absolute drive reference refused")
    return ref


def safe_path(root, ref, must_file=False):
    root = Path(os.path.abspath(root))
    path = root / safe_ref(ref)
    for item in (root, *[root.joinpath(*Path(ref).parts[:i]) for i in range(1, len(Path(ref).parts) + 1)]):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "linked path refused")
    require(path.resolve() == path and path.is_relative_to(root), "path escapes root")
    if must_file:
        require(path.is_file(), "missing file: " + ref)
    return path


def local(path):
    path = Path(os.path.abspath(path))
    require(path != ROOT / ".local" and path.is_relative_to(ROOT / ".local"), "output must be below project .local")
    return safe_path(ROOT, path.relative_to(ROOT).as_posix())


def recheck_map(values, root=ROOT):
    require(type(values) is dict and values, "empty source inventory")
    for ref, sha in values.items():
        require(type(sha) is str and re.fullmatch(r"[a-f0-9]{64}", sha), "invalid digest")
        require(digest(safe_path(root, ref, True)) == sha, "changed source/artifact: " + ref)


def canonical_sources():
    recheck_map(PINNED)
    return dict(PINNED)


def adapter_path():
    require(Path(__file__).resolve() == safe_path(ROOT, ADAPTER_REF, True), "adapter is outside its project module")
    return Path(__file__).resolve()


def helpers():
    canonical_sources()  # Verify bytes before importing any delegated implementation.
    for directory in (ROOT / "transport", ROOT / "tools"):
        if str(directory) not in sys.path:
            sys.path.insert(0, str(directory))
    h = importlib.import_module("handoff")
    cs = importlib.import_module("cs137")
    s = importlib.import_module("scenario_prepare")
    gamma = importlib.import_module("scenario_transport")
    ring = importlib.import_module("ring_cs137")
    models = importlib.import_module("ring_model_contract")
    s.native_helpers()  # Existing helper initialization; no constants/functions are replaced.
    require(h.ROOT == s.ROOT == cs.HERE.parent == models.ROOT == ROOT, "helper root mismatch")
    return h, cs, s, gamma, ring, models


def closed_request(value):
    require(type(value) is dict and set(value) == {"detector", "source_mode", "source_pose", "primary_count", "seed"}, "unsupported request keys")
    require(type(value["detector"]) is str and value["detector"] in DETECTORS, "unsupported detector")
    require(type(value["source_mode"]) is str and value["source_mode"] in (CS137, GAMMA), "unsupported source mode")
    require(type(value["primary_count"]) is int and type(value["seed"]) is int
            and 0 < value["seed"] < 2147483647, "invalid primary count/seed")
    if value["source_mode"] == GAMMA:
        exact([value["detector"] in ("AK02", "SAP22"), value["source_pose"], value["primary_count"], value["seed"]],
              [True, "plus5mm", 20, 26092631], "unsupported fixed gamma tuple")
    else:
        require(value["source_pose"] == "nominal" and value["primary_count"] in (20, 500), "unsupported Cs137 tuple")
    return dict(value)


def model_id(request):
    return "GeRC02" if request["detector"] == "GeRC02_Li50min" else request["detector"]


def ring_case(request):
    return request["detector"] in ("GeRC02_Li50min", "KMRC01_candidate")


def command(request):
    return ["remage", "--flat-output", "-t", "1", "--rand-seed", str(request["seed"]),
            "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"]


def locked_packages():
    canonical_sources()
    import yaml
    lock = yaml.safe_load((ROOT / "transport/pixi.lock").read_bytes())
    require(lock["version"] == 7, "unsupported frozen lock format")
    urls = {p["conda"] for p in lock["environments"]["default"]["packages"]["linux-64"]}
    packages = {}
    for name in PACKAGE_NAMES:
        selected = [p for p in lock["packages"] if p.get("conda") in urls
                    and Path(p["conda"]).name.startswith(name + "-")
                    and re.fullmatch(re.escape(name) + r"-[^-]+-[^-]+\.(conda|tar\.bz2)", Path(p["conda"]).name)]
        require(len(selected) == 1, "missing/ambiguous locked package: " + name)
        p = selected[0]
        match = re.fullmatch(re.escape(name) + r"-([^-]+)-([^-]+)\.(conda|tar\.bz2)", Path(p["conda"]).name)
        packages[name] = {"name": name, "version": match[1], "build": match[2],
                          "url": p["conda"], "archive_sha256": p["sha256"]}
    return packages


def package_record(prefix, wanted):
    found = []
    for path in (prefix / "conda-meta").glob(wanted["name"] + "-*.json"):
        # The package name prefix can match gcc_linux-64 vs other names; parse name exactly.
        package = load(path)
        if package.get("name") == wanted["name"]:
            found.append((path, package))
    require(len(found) == 1, "missing/ambiguous installed package: " + wanted["name"])
    path, package = found[0]
    exact({key: package.get(key) for key in ("name", "version", "build")},
          {key: wanted[key] for key in ("name", "version", "build")}, "installed package differs from lock")
    require(package.get("sha256") == wanted["archive_sha256"] and package.get("url") == wanted["url"], "installed archive identity differs from lock")
    safe_path(prefix, path.relative_to(prefix).as_posix(), True)
    return {**wanted, "metadata_ref": path.relative_to(prefix).as_posix(), "metadata_sha256": digest(path)}


def executable(prefix, name, version=None):
    found = shutil.which(name)
    require(found is not None, "missing locked executable: " + name)
    path = Path(found).resolve()
    require(path.is_relative_to(prefix), "executable outside locked prefix: " + name)
    require(path.is_file(), "missing runtime executable")
    argv = [str(path), "--version"]
    result = subprocess.run(argv, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, shell=False)
    if version is not None:
        require(result.stdout.strip() == version, "locked runtime version mismatch: " + name)
    return {"ref": path.relative_to(prefix).as_posix(), "sha256": digest(path), "version_output": result.stdout.strip(), "version_argv": argv}


def runtime_snapshot():
    require(platform.system() == "Linux", "portable source stages require existing locked WSL Linux runtime")
    prefix = Path(sys.prefix).resolve()
    require(os.environ.get("CONDA_PREFIX") and Path(os.environ["CONDA_PREFIX"]).resolve() == prefix, "active locked prefix mismatch")
    require(os.environ.get("PIXI_PROJECT_MANIFEST") and Path(os.environ["PIXI_PROJECT_MANIFEST"]).resolve() == ROOT / "transport/pixi.toml", "not the existing project Pixi runtime")
    packages = {name: package_record(prefix, item) for name, item in locked_packages().items()}
    require(platform.python_version() == packages["python"]["version"], "Python version differs from lock")
    exes = {"python": {"ref": Path(sys.executable).resolve().relative_to(prefix).as_posix(), "sha256": digest(sys.executable), "version_output": platform.python_version(), "version_argv": None}}
    for name, version in (("remage", "1.1.0"), ("geant4-config", "11.3.2"), ("cmake", None), ("ninja", None)):
        exes[name] = executable(prefix, name, version)
    require(exes["ninja"]["version_output"] == packages["ninja"]["version"], "Ninja version differs from lock")
    require(exes["cmake"]["version_output"].splitlines()[0] == "cmake version " + packages["cmake"]["version"], "CMake version differs from lock")
    return {"kind": "portable_locked_runtime_v1", "prefix": str(prefix), "lock_sha256": PINNED["transport/pixi.lock"], "packages": packages, "executables": exes}


def recheck_runtime(saved):
    exact(runtime_snapshot(), saved, "runtime/package/executable changed since admission")


def project_identity(windows_root):
    require(type(windows_root) is str and re.match(r"^[A-Za-z]:[\\/]", windows_root), "canonical Windows root must be supplied by launcher")
    output = subprocess.run(["wslpath", "-w", str(ROOT)], text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.PIPE, check=True, shell=False).stdout.strip()
    normalize = lambda v: v.replace("/", "\\").rstrip("\\")
    require(normalize(windows_root) == normalize(output), "Windows/Linux project roots disagree")
    return {"windows_root": normalize(output), "linux_root": str(ROOT), "compiled_project_local": str(ROOT / ".local")}


def build_recipe(runtime):
    prefix = Path(runtime["prefix"])
    cmake = str(prefix / runtime["executables"]["cmake"]["ref"])
    ninja = str(prefix / runtime["executables"]["ninja"]["ref"])
    compiler = shutil.which(os.environ.get("CXX", ""))
    require(compiler is not None and Path(compiler).resolve().is_relative_to(prefix), "missing locked CXX compiler")
    compiler = str(Path(compiler).resolve())
    flags = build_flags(prefix)
    configure = [cmake, "-S", str(ROOT / "transport"), "-B", str(ROOT / BUILD_REF), "-G", "Ninja",
                 "-DCMAKE_BUILD_TYPE=Release", "-DCMAKE_EXPORT_COMPILE_COMMANDS=ON",
                 "-DCMAKE_CXX_COMPILER=" + compiler, "-DCMAKE_MAKE_PROGRAM=" + ninja,
                 *("-D" + key + "=" + value for key, value in flags.items()),
                 "-DGeant4_DIR=" + str(prefix / "lib/cmake/Geant4")]
    build = [cmake, "--build", str(ROOT / BUILD_REF), "--target", "cryostat_export", "--parallel", "1", "--verbose"]
    return {"configure_argv": configure, "build_argv": build, "cwd": str(ROOT), "generator": "Ninja", "target": "cryostat_export", "compiler": compiler}


def build_flags(prefix):
    # The frozen locked toolchain's established flags, with only clone-prefix relocation.
    # Passing them explicitly prevents CXXFLAGS/LDFLAGS or rehashed cache changes from
    # silently selecting an unreviewed compiler recipe. No environment variable is edited.
    prefix = Path(prefix)
    return {"CMAKE_CXX_FLAGS": "-fvisibility-inlines-hidden -fmessage-length=0 -march=nocona -mtune=haswell -ftree-vectorize -fPIC -fstack-protector-strong -fno-plt -O2 -ffunction-sections -pipe -isystem " + str(prefix / "include"),
            "CMAKE_CXX_FLAGS_RELEASE": "-O3 -DNDEBUG",
            "CMAKE_EXE_LINKER_FLAGS": "-Wl,-O2 -Wl,--sort-common -Wl,--as-needed -Wl,-z,relro -Wl,-z,now -Wl,--disable-new-dtags -Wl,--gc-sections -Wl,--allow-shlib-undefined -Wl,-rpath," + str(prefix / "lib") + " -Wl,-rpath-link," + str(prefix / "lib") + " -L" + str(prefix / "lib"),
            "CMAKE_EXE_LINKER_FLAGS_RELEASE": ""}


def cache_fields(path):
    fields = {}
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line or line.startswith(("#", "//")):
            continue
        match = re.match(r"^([^:=]+):[^=]+=(.*)$", line)
        if match:
            require(match[1] not in fields, "duplicate CMake cache key")
            fields[match[1]] = match[2]
    return fields


def validate_link_command(commands_text, recipe, runtime):
    """The frozen one-source target has one compile and one ordinary link action."""
    lines = [line for line in commands_text.splitlines() if line.strip()]
    require(len(lines) == 2, "extra/missing target build action")
    links = [shlex.split(line) for line in lines if "-o cryostat_export" in line]
    require(len(links) == 1, "missing/ambiguous exporter link action")
    tokens = links[0]
    require(tokens[:2] == [":", "&&"] and tokens[-2:] == ["&&", ":"], "extra target link shell action")
    argv = tokens[2:-2]
    require(Path(argv[0]).resolve() == Path(recipe["compiler"]), "foreign target link driver")
    object_ref = "CMakeFiles/cryostat_export.dir/cryostat_export.cc.o"
    require(argv.count(object_ref) == 1 and argv.count("-o") == 1 and argv[argv.index("-o") + 1] == "cryostat_export", "wrong exporter link object/output")
    flags = build_flags(runtime["prefix"])
    allowed = set(shlex.split(" ".join(flags.values()))) | {"-pthread", "-fPIC", "-ldl", "-lpthread", "-lrt", "-lm",
                "-Wl,--dependency-file=CMakeFiles/cryostat_export.dir/link.d"}
    prefix = Path(runtime["prefix"])
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg == "-o":
            i += 2
        elif arg == "-isystem":
            require(i + 1 < len(argv) and Path(argv[i + 1]) == prefix / "include", "foreign link include path")
            i += 2
        elif arg == object_ref or arg in allowed:
            i += 1
        elif arg.startswith("-Wl,-rpath,"):
            require(arg.removeprefix("-Wl,-rpath,").rstrip(":") == str(prefix / "lib"), "foreign generated link rpath")
            i += 1
        else:
            path = Path(arg)
            require(path.is_absolute() and path.resolve().is_relative_to(prefix) and
                    re.fullmatch(r"lib[A-Za-z0-9_.+-]+\.(?:a|so(?:\.[0-9.]+)?)", path.name), "extra linker option/input refused: " + arg)
            i += 1
    return argv


def build_semantics(recipe, runtime):
    build = safe_path(ROOT, BUILD_REF)
    fields = cache_fields(build / "CMakeCache.txt")
    wanted = {"CMAKE_HOME_DIRECTORY": str(ROOT / "transport"), "CMAKE_CACHEFILE_DIR": str(build),
              "CMAKE_GENERATOR": "Ninja", "CMAKE_BUILD_TYPE": "Release", "CMAKE_CXX_COMPILER": recipe["compiler"],
              "CMAKE_MAKE_PROGRAM": str(Path(runtime["prefix"]) / runtime["executables"]["ninja"]["ref"]),
              "CMAKE_EXPORT_COMPILE_COMMANDS": "ON", "CMAKE_PROJECT_NAME": "m2a_geometry_probe",
              "Geant4_DIR": str(Path(runtime["prefix"]) / "lib/cmake/Geant4"), **build_flags(runtime["prefix"])}
    exact({key: fields.get(key) for key in wanted}, wanted, "foreign/overridden CMake cache")
    for key in ("CMAKE_CXX_STANDARD_LIBRARIES", "CMAKE_CXX_COMPILER_ARG1", "CMAKE_TOOLCHAIN_FILE",
                "CMAKE_CXX_COMPILER_LAUNCHER", "CMAKE_LINKER_LAUNCHER", "CMAKE_PROJECT_INCLUDE",
                "CMAKE_PROJECT_INCLUDE_BEFORE", "CMAKE_USER_MAKE_RULES_OVERRIDE"):
        require(not fields.get(key), "extra CMake build override refused: " + key)
    prefix = Path(runtime["prefix"])
    require(fields.get("Geant4_DIR") and Path(fields["Geant4_DIR"]).resolve().is_relative_to(prefix), "Geant4 configuration outside locked prefix")
    require(fields.get("CMAKE_LINKER") and Path(fields["CMAKE_LINKER"]).resolve().is_relative_to(prefix), "linker outside locked prefix")
    commands = load(build / "compile_commands.json")
    selected = [item for item in commands if Path(item["file"]).resolve() == ROOT / "transport/cryostat_export.cc"]
    require(len(selected) == 1 and selected[0]["directory"] == str(build), "wrong cryostat_export compile target/root")
    argv = selected[0].get("arguments") or shlex.split(selected[0]["command"])
    require(Path(argv[0]).resolve() == Path(recipe["compiler"]), "foreign compiler in target command")
    definitions = [arg for arg in argv if arg.startswith("-DPROJECT_LOCAL=")]
    exact(definitions, ['-DPROJECT_LOCAL="' + str(ROOT / ".local") + '"'], "wrong compiled PROJECT_LOCAL")
    require(argv.count("-c") == 1 and Path(argv[argv.index("-c") + 1]).resolve() == ROOT / "transport/cryostat_export.cc", "wrong compile source")
    require(argv.count("-o") == 1 and argv[argv.index("-o") + 1] == "CMakeFiles/cryostat_export.dir/cryostat_export.cc.o", "wrong target object")
    require(not any(arg.startswith(("@", "-include", "-imacros", "-fplugin", "-specs=", "--sysroot=")) for arg in argv), "extra compiler injection refused")
    # These are the target definitions exported by the pinned Geant4/Qt build.
    expected_definitions = {definitions[0], *["-D" + v for v in (
        "G4LIB_BUILD_DLL", "G4UI_USE_QT", "G4VIS_USE_RAYTRACERX", "G4VIS_USE_TOOLSSG_QT_GLES",
        "G4VIS_USE_TOOLSSG_QT_ZB", "G4VIS_USE_TOOLSSG_X11_GLES", "G4VIS_USE_TOOLSSG_X11_ZB",
        "NDEBUG", "PTL_BUILD_DLL", "QT_CORE_LIB", "QT_GUI_LIB", "QT_NO_DEBUG", "QT_WIDGETS_LIB",
        "TOOLS_USE_HDF5", "_FORTIFY_SOURCE=2")]}
    require(set(arg for arg in argv if arg.startswith("-D")) == expected_definitions, "target definitions differ from locked build")
    allowed_flags = set(shlex.split(build_flags(prefix)["CMAKE_CXX_FLAGS"])) | {"-O3", "-DNDEBUG", "-pthread", "-fPIC", "-std=gnu++17", "-std=c++17"}
    i = 1
    while i < len(argv):
        arg = argv[i]
        if arg in ("-c", "-o"):
            i += 2
        elif arg == "-isystem":
            require(i + 1 < len(argv) and Path(argv[i + 1]).resolve().is_relative_to(prefix), "foreign target include directory")
            i += 2
        else:
            require(arg in expected_definitions or arg in allowed_flags, "extra compiler option refused: " + arg)
            i += 1
    commands_text = (build / "target-commands.txt").read_text(encoding="utf-8")
    require("cryostat_export.cc" in commands_text and "-o cryostat_export" in commands_text
            and str(ROOT / "transport/cryostat_export.cc") in commands_text, "missing actual target compile/link evidence")
    link_argv = validate_link_command(commands_text, recipe, runtime)
    compiler_record = executable(prefix, recipe["compiler"])
    linker_record = executable(prefix, fields["CMAKE_LINKER"])
    compiler_files = list((build / "CMakeFiles").glob("*/CMakeCXXCompiler.cmake"))
    require(len(compiler_files) == 1, "missing/ambiguous compiler identification")
    compiler_text = compiler_files[0].read_text(encoding="utf-8")
    require('set(CMAKE_CXX_COMPILER_ID "GNU")' in compiler_text
            and 'set(CMAKE_CXX_COMPILER_VERSION "' + runtime["packages"]["gxx_impl_linux-64"]["version"] + '")' in compiler_text, "compiler ID/version differs from lock")
    evidence_files = ["CMakeCache.txt", "build.ninja", "CMakeFiles/rules.ninja", "compile_commands.json",
                      "configure.log", "build.log", "target-commands.txt", compiler_files[0].relative_to(build).as_posix()]
    return {"cache_identity": wanted, "compiler_identity": compiler_record, "linker_identity": linker_record,
            "target_compile_argv": argv, "target_link_argv": link_argv,
            "evidence_sha256": {BUILD_REF + "/" + ref: digest(safe_path(build, ref, True)) for ref in evidence_files}}


def check_build_environment(runtime):
    """Accept only the pinned compiler's ordinary Pixi activation hints."""
    prefix = runtime["prefix"]
    expected = {"CMAKE_" + key: prefix + "/bin/x86_64-conda-linux-gnu-" + value
                for key, value in (("AR", "ar"), ("CXX_COMPILER_AR", "gcc-ar"),
                                   ("C_COMPILER_AR", "gcc-ar"), ("RANLIB", "ranlib"),
                                   ("CXX_COMPILER_RANLIB", "gcc-ranlib"),
                                   ("C_COMPILER_RANLIB", "gcc-ranlib"),
                                   ("LINKER", "ld"), ("STRIP", "strip"))}
    expected["CMAKE_BUILD_TYPE"] = "Release"
    hints = os.environ.get("CMAKE_ARGS", "")
    if hints:
        actual = {}
        for token in shlex.split(hints):
            require(token.startswith("-D") and "=" in token, "external build override refused: CMAKE_ARGS")
            key, value = token[2:].split("=", 1)
            require(key not in actual, "duplicate build activation hint")
            actual[key] = value
        exact(actual, expected, "external build override refused: CMAKE_ARGS")
    for variable in ("CMAKE_GENERATOR", "CMAKE_TOOLCHAIN_FILE", "CMAKE_PROJECT_INCLUDE", "CMAKE_PROJECT_INCLUDE_BEFORE"):
        require(not os.environ.get(variable), "external build override refused: " + variable)
    require(os.environ.get("CMAKE_PREFIX_PATH", "") in
            ("", prefix, prefix + ":" + prefix + "/x86_64-conda-linux-gnu/sysroot/usr"),
            "foreign build prefix override")


def build_exporter(windows_root):
    """Only the actual fixed successful build action emits exporter-build.json."""
    producer = digest(adapter_path())
    sources = canonical_sources()
    identity = project_identity(windows_root)
    runtime = runtime_snapshot()
    check_build_environment(runtime)
    recipe = build_recipe(runtime)
    destination = safe_path(ROOT, BUILD_REF)
    if destination.exists():
        return read_build_receipt(windows_root)  # Never adopt an incomplete directory or arbitrary executable.
    destination.mkdir(parents=True)
    h, *_ = helpers()
    attempt = {"kind": "portable_exporter_build_attempt_v1", "status": "failed", "project_identity": identity, "recipe": recipe}
    start = time.perf_counter()
    try:
        for stage in ("configure", "build"):
            recheck_map(sources); recheck_runtime(runtime)
            require(digest(adapter_path()) == producer, "adapter changed during build")
            with (destination / (stage + ".log")).open("x", encoding="utf-8") as log:
                t = time.perf_counter()
                result = subprocess.run(recipe[stage + "_argv"], cwd=ROOT, stdout=log, stderr=subprocess.STDOUT, shell=False, check=False)
                attempt[stage + "_wall_s"] = time.perf_counter() - t
            attempt[stage + "_returncode"] = result.returncode
            require(type(result.returncode) is int and result.returncode == 0, "fixed exporter build failed; preserve attempt")
        ninja = Path(runtime["prefix"]) / runtime["executables"]["ninja"]["ref"]
        with (destination / "target-commands.txt").open("x", encoding="utf-8") as log:
            subprocess.run([str(ninja), "-C", str(destination), "-t", "commands", "cryostat_export"], stdout=log, stderr=subprocess.STDOUT, check=True, shell=False)
        semantics = build_semantics(recipe, runtime)
        recheck_map(sources); recheck_runtime(runtime)
        require(digest(adapter_path()) == producer, "producer changed during fixed build")
        binary = safe_path(ROOT, EXPORTER_REF, True)
        receipt = {"kind": "portable_source_exporter_build_v1", "schema_version": 1, "status": "complete", "adapter_version": VERSION,
                   "producer_sha256": producer, "project_identity": identity, "source_sha256": sources, "runtime": runtime,
                   "build": {**recipe, **semantics, **{key: attempt[key] for key in ("configure_returncode", "build_returncode", "configure_wall_s", "build_wall_s")}},
                   "exporter": {"ref": EXPORTER_REF, "bytes": binary.stat().st_size, "sha256": digest(binary)}}
        validate_build_receipt(receipt, identity, runtime, producer, recipe, semantics)
        h.publish_json(ROOT / BUILD_RECEIPT_REF, receipt)
        attempt["status"] = "complete"
        return receipt
    except Exception as error:
        attempt["error"] = str(error)
        raise
    finally:
        attempt["total_wall_s"] = time.perf_counter() - start
        h.publish_json(destination / "build-attempt.json", attempt)


def validate_build_receipt(value, identity, runtime, producer, recipe, semantics):
    require(type(value) is dict and set(value) == BUILD_KEYS, "unsupported build receipt keys")
    exact([value["kind"], value["schema_version"], value["status"], value["adapter_version"]],
          ["portable_source_exporter_build_v1", 1, "complete", VERSION], "incomplete/unknown build receipt")
    exact(value["project_identity"], identity, "foreign project build receipt")
    exact(value["source_sha256"], PINNED, "rehashing cannot admit changed canonical source")
    exact(value["runtime"], runtime, "foreign build runtime/lock identity")
    require(value["producer_sha256"] == producer, "build producer changed")
    expected_build = {**recipe, **semantics}
    require(set(value["build"]) == set(expected_build) | {"configure_returncode", "build_returncode", "configure_wall_s", "build_wall_s"}, "unsupported build recipe keys")
    for key, expected in expected_build.items():
        exact(value["build"][key], expected, "changed build recipe/target: " + key)
    for stage in ("configure", "build"):
        exact(value["build"][stage + "_returncode"], 0, "unsuccessful build stage")
        timing = value["build"][stage + "_wall_s"]
        require(type(timing) in (int, float) and math.isfinite(timing) and timing >= 0, "invalid build timing")
    require(type(value["exporter"]) is dict and set(value["exporter"]) == {"ref", "bytes", "sha256"}
            and value["exporter"]["ref"] == EXPORTER_REF and type(value["exporter"]["bytes"]) is int
            and value["exporter"]["bytes"] > 0 and type(value["exporter"]["sha256"]) is str
            and re.fullmatch(r"[a-f0-9]{64}", value["exporter"]["sha256"]), "invalid clone-local exporter record")
    return value


def read_build_receipt(windows_root):
    canonical_sources()
    producer = digest(adapter_path())
    identity = project_identity(windows_root)
    runtime = runtime_snapshot()
    recipe = build_recipe(runtime)
    semantics = build_semantics(recipe, runtime)
    value = load(safe_path(ROOT, BUILD_RECEIPT_REF, True))
    validate_build_receipt(value, identity, runtime, producer, recipe, semantics)
    recheck_map(value["build"]["evidence_sha256"])
    binary = safe_path(ROOT, EXPORTER_REF, True)
    exact(value["exporter"], {"ref": EXPORTER_REF, "bytes": binary.stat().st_size, "sha256": digest(binary)}, "changed clone-local exporter bytes")
    attempt = load(safe_path(ROOT, BUILD_REF + "/build-attempt.json", True))
    require(set(attempt) == {"kind", "status", "project_identity", "recipe", "configure_wall_s", "configure_returncode", "build_wall_s", "build_returncode", "total_wall_s"} and
            attempt["kind"] == "portable_exporter_build_attempt_v1" and attempt["status"] == "complete" and attempt["project_identity"] == identity and attempt["recipe"] == recipe,
            "missing matching completed fixed build attempt")
    for key in ("configure_returncode", "build_returncode", "configure_wall_s", "build_wall_s"):
        exact(attempt[key], value["build"][key], "build attempt/receipt changed: " + key)
    require(type(attempt["total_wall_s"]) in (int,float) and math.isfinite(attempt["total_wall_s"]) and attempt["total_wall_s"] >= 0, "invalid total build time")
    return value


def file_readiness(root=ROOT):
    """Windows UI file check only; the WSL Check independently proves runtime/build."""
    root = Path(root).resolve()
    recheck_map(PINNED, root)
    value = load(safe_path(root, BUILD_RECEIPT_REF, True))
    require(set(value) == BUILD_KEYS and value["kind"] == "portable_source_exporter_build_v1" and
            value["schema_version"] == 1 and value["status"] == "complete" and value["adapter_version"] == VERSION, "incomplete portable build receipt")
    exact(value["source_sha256"], PINNED, "canonical build sources changed")
    require(value["producer_sha256"] == digest(safe_path(root, ADAPTER_REF, True)), "portable build producer changed")
    normalize = lambda v: v.replace("/", "\\").rstrip("\\")
    require(normalize(value["project_identity"]["windows_root"]) == normalize(str(root)), "foreign Windows build root")
    binary = safe_path(root, EXPORTER_REF, True)
    exact(value["exporter"], {"ref": EXPORTER_REF, "bytes": binary.stat().st_size, "sha256": digest(binary)}, "portable exporter changed")
    evidence = value["build"]["evidence_sha256"]
    require(type(evidence) is dict and evidence and all(ref.startswith(BUILD_REF + "/") for ref in evidence), "foreign build evidence")
    recheck_map(evidence, root)
    attempt = load(safe_path(root, BUILD_REF + "/build-attempt.json", True))
    require(attempt["kind"] == "portable_exporter_build_attempt_v1" and attempt["status"] == "complete" and
            attempt["project_identity"] == value["project_identity"] and
            attempt["recipe"] == {key: value["build"][key] for key in ("configure_argv", "build_argv", "cwd", "generator", "target", "compiler")}, "portable build attempt incomplete/foreign")
    return {"available": True, "build_receipt_ref": BUILD_RECEIPT_REF, "build_receipt_sha256": digest(root / BUILD_RECEIPT_REF)}


def execution_binding(request, build):
    producer = digest(adapter_path())
    marker = {"kind": EXECUTION_KIND, "version": VERSION, "source_mode": request["source_mode"],
              "adapter_ref": ADAPTER_REF, "adapter_sha256": producer,
              "build_receipt_ref": BUILD_RECEIPT_REF, "build_receipt_sha256": digest(ROOT / BUILD_RECEIPT_REF),
              "exporter_ref": EXPORTER_REF, "exporter_sha256": build["exporter"]["sha256"], "exporter_bytes": build["exporter"]["bytes"]}
    inventory = {ADAPTER_REF: producer, BUILD_RECEIPT_REF: marker["build_receipt_sha256"], EXPORTER_REF: marker["exporter_sha256"]}
    return marker, inventory


def validate_execution_binding(marker, portable, expected_marker, expected_portable):
    exact(marker, expected_marker, "absent/unknown/mixed portable execution marker")
    exact(portable, expected_portable, "portable source map/binding changed")


def check(request, windows_root):
    request = closed_request(request)
    build = read_build_receipt(windows_root)
    marker, portable = execution_binding(request, build)
    h, cs, s, gamma, ring, models = helpers()
    if request["source_mode"] == GAMMA:
        config = ROOT / f"scenarios/m11a-{request['detector'].lower()}-mono_gamma_662_axis_v1-plus5mm.json"
        resolved = s.check(config)
        exact([resolved["instance"]["primary_count"], resolved["instance"]["seed"], resolved["instance"]["source_pose"]],
              [20, 26092631, "plus5mm"], "canonical gamma config changed")
    else:
        resolved = None
        if ring_case(request):
            models.inputs(model_id(request))
            ring.scenario()
        else:
            h.load_model(model_id(request))
    return {"kind": "portable_source_checked_plan_v1", "schema_version": 1, "request": request,
            "execution_contract": marker, "portable_source_sha256": portable, "canonical_source_sha256": canonical_sources(),
            "upstream_sha256": cs.upstream_hashes(), "runtime": build["runtime"], "gamma_plan": resolved}


def validate_checked_plan(saved, request, windows_root):
    actual = check(request, windows_root)
    exact(saved, actual, "checked plan changed; repeat Check before Start")
    return actual


def runtime_data(directory, runtime, source_mode):
    """Record required datasets in this output root; retain existing EMLOW algorithm."""
    h, cs, s, gamma, *_ = helpers()
    prefix = Path(runtime["prefix"])
    require("G4LEDATA" in os.environ, "missing installed EMLOW data")
    emlow = Path(os.environ["G4LEDATA"]).resolve()
    require(emlow.is_relative_to(prefix), "EMLOW outside locked prefix")
    metadata = prefix / runtime["packages"]["geant4-data-emlow"]["metadata_ref"]
    record = gamma.emlow_manifest(emlow, metadata)
    dest = local(directory / "runtime")
    require(not dest.exists(), "runtime evidence output exists")
    dest.mkdir()
    h.publish_json(dest / "emlow-data.json", record)
    values = {"identity": runtime, "emlow_manifest": str(dest / "emlow-data.json"),
              "emlow_manifest_sha256": digest(dest / "emlow-data.json"), "decay_data": None,
              "emlow_verification_wall_s": record["hash_wall_s"]}
    if source_mode == CS137:
        packages = {"G4RADIOACTIVEDATA": "geant4-data-radioactivedecay",
                    "G4LEVELGAMMADATA": "geant4-data-photonevaporation", "G4ENSDFSTATEDATA": "geant4-data-ensdfstate"}
        values["decay_data"] = {"required_files": cs.installed_data(), "datasets": {}}
        for variable, name in packages.items():
            require(variable in os.environ, "missing installed decay data: " + variable)
            path = Path(os.environ[variable]).resolve()
            require(path.is_dir() and path.is_relative_to(prefix), "decay dataset outside locked prefix")
            safe_path(prefix, path.relative_to(prefix).as_posix())
            values["decay_data"]["datasets"][variable] = {"directory": str(path), "package": runtime["packages"][name]}
    h.publish_json(dest / "runtime.json", values)
    return values


def recheck_runtime_data(values, source_mode):
    h, cs, s, gamma, *_ = helpers()
    recheck_runtime(values["identity"])
    elapsed = gamma.recheck_data(values)
    if source_mode == CS137:
        require(type(values["decay_data"]) is dict, "missing decay data binding")
        exact(values["decay_data"]["required_files"], cs.installed_data(), "required decay bytes changed")
        names = {"G4RADIOACTIVEDATA": "geant4-data-radioactivedecay",
                 "G4LEVELGAMMADATA": "geant4-data-photonevaporation", "G4ENSDFSTATEDATA": "geant4-data-ensdfstate"}
        require(set(values["decay_data"]["datasets"]) == set(names), "decay data census changed")
        for variable, package in names.items():
            expected = {"directory": str(Path(os.environ[variable]).resolve()), "package": values["identity"]["packages"][package]}
            exact(values["decay_data"]["datasets"][variable], expected, "decay prefix/package/environment changed")
    else:
        exact(values["decay_data"], None, "gamma decay-data binding changed")
    return elapsed


def geometry_contract(request, gamma_plan):
    h, cs, s, gamma, ring, models = helpers()
    model = model_id(request)
    if ring_case(request):
        points = ring.contour(model)
        scenario = ring.scenario()
        probes = ring.probes(model, points)
        model_doc = models.inputs(model)[1]
    else:
        model_doc, points = h.load_model(model)
        scenario = s.strict_load(ROOT / "transport/cryostat_nominal.json")
        probes = h.probe_points(points)
        exact(model_doc["detectors"][0]["semiconductor"]["temperature"], 78, "original temperature changed")
        exact([[c["id"], c["potential"]] for c in model_doc["detectors"][0]["contacts"]],
              [[1, 0], [2, 500 if model == "AK02" else 700]], "original contact/bias changed")
    source = gamma_plan["source_position_global_mm"] if gamma_plan else scenario["source"]["position_global_mm"]
    plan = None
    if gamma_plan:
        plan = {**gamma_plan, "contour_rz_mm": points}
    return model_doc, points, scenario, probes, source, plan


def parameter_text(scenario, source, gamma_mode):
    sp, cap = scenario["spacer"], scenario["capsule"]
    values = [*scenario["coordinate_transform"]["translation_global_mm"], *scenario["expected_vacuum_global_translation_mm"],
              *sp["vacuum_centre_mm"], sp["radius_mm"], sp["thickness_mm"], *source,
              cap["radius_mm"], cap["thickness_mm"], cap["wall_mm"], scenario["overlap_samples"]]
    require(len(values) == 18, "native parameter census changed")
    # Keep the exact old gamma versus Cs137 serialization conventions.
    return " ".join(format(v, ".17g") if gamma_mode else str(v) for v in values) + "\n"


def probe_text(probes):
    return "".join(" ".join(format(x, ".17g") for x in p["position_mm"]) + "\n" for p in probes)


def geometry_command(directory):
    return [str(ROOT / EXPORTER_REF), str(ROOT / ".local/transport/LBNL/stage.tg"),
            *(str(directory / ref) for ref in ("canonical.gdml", "probe-points.txt", "parameters.txt", "geometry.gdml", "geometry-report.json"))]


def validate_geometry(report, request, scenario, plan, probes):
    _, _, s, _, ring, _ = helpers()
    if ring_case(request):
        ring.validate_report(report, model_id(request), scenario, probes)
    else:
        # The full legacy assembly validator also serves nominal AK/SAP Cs137.
        full_plan = plan or {"assets": {"detector": {"id": model_id(request)}},
                             "coordinate_transform": scenario["coordinate_transform"],
                             "source_position_global_mm": scenario["source"]["position_global_mm"]}
        s.validate_report(report, full_plan, probes)


def metadata_for(directory, checked, report, model_contract, elapsed, files):
    """Schema serialization only; no geometry, timing, parsing or grouping kernel."""
    h, cs, s, gamma, ring, models = helpers()
    request = checked["request"]
    model = model_id(request)
    _, points, scenario, probes, source, plan = geometry_contract(request, checked["gamma_plan"])
    common = {"model_id": model, "coordinate_transform": scenario["coordinate_transform"], "contour_rz_mm": points,
              "exporter_sha256": checked["execution_contract"]["exporter_sha256"], "upstream_sha256": checked["upstream_sha256"],
              "material_tables": {"stp/" + v["name"]: v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"},
              "files_sha256": files, "execution_contract": checked["execution_contract"],
              "portable_source_sha256": checked["portable_source_sha256"]}
    if request["source_mode"] == CS137 and not ring_case(request):
        # The frozen AK/SAP Julia reader admits only basename entries in this
        # legacy map. The new paired reader owns the additional nested evidence.
        common["files_sha256"] = {ref: sha for ref, sha in files.items() if "/" not in ref}
        common["portable_files_sha256"] = {ref: sha for ref, sha in files.items() if "/" in ref}
    if request["source_mode"] == GAMMA:
        config = ROOT / f"scenarios/m11a-{model.lower()}-mono_gamma_662_axis_v1-plus5mm.json"
        return {**common, "kind": s.KIND, "schema_version": 1, "status": "prepared", "instance": plan["instance"], "assets": plan["assets"],
                "source_position_global_mm": source, "source_pose_status": "native geometry checked for this preparation; nominal engineering pose",
                "stages": {"geometry": "geometry_checked", "source_macro": "source_macro_prepared", "transport": "transport_not_executed", "charge": "charge_not_executed", "readout": "readout_not_executed"},
                "source_sha256": s.frozen_inventory(config, ROOT / EXPORTER_REF), "legacy_source_sha256": cs.source_hashes(),
                "versions": {**h.python_versions(), "geant4_version_number": report["geant4_version_number"]},
                "overlap_seed": 26092632, "overlap_samples": 10000, "grouping_policy": {**cs.POLICY, "horizon_ns": scenario["group_horizon_ns"]},
                "energy_closure": None, "activity_Bq": None,
                "assumptions": [scenario["status"], "baseline nominal top reference: " + scenario["top_assumption"],
                    "selected pose plus5mm; plus5mm is 5 mm beyond the nominal capsule/source centre along global +y",
                    "source point and capsule/fill move together; capsule axis global +y", "overlap sampling is not geometry convergence",
                    "planned count/seed/macro are inputs; no emitted event census or raw quantities exist"],
                "unknowns": scenario["unknowns"], "omitted": scenario["omitted"],
                "unscored_volumes": [{"name": "ledger_0_PV", "material": "G4_AIR", "reason": "world is unscored; world/escape/neutrino energy closure not established"}],
                "native_geometry_wall_s": elapsed}
    base = {**common, "kind": ring.PREPARED_KIND if ring_case(request) else "cs137_prepared_v1",
            "model_sha256": model_contract["source_model_sha256"] if model_contract else h.PINNED[model],
            "primary_count": request["primary_count"], "seed": request["seed"], "source_pdg": cs.ION,
            "source_position_global_mm": source, "clock_policy": "remage_initial_decay_secondaries_zero", "daughter_lifetime_limit_ns": -1,
            "grouping_policy": dict(cs.POLICY), "decay_photon_line_window_keV": scenario["decay_photon_line_window_keV"],
            "source_sha256": cs.source_hashes(),
            "unscored_volumes": [{"name": "ledger_0_PV", "material": "G4_AIR", "reason": "unscored default world region; no full energy closure claim"}] if ring_case(request) else
                [{"name": "ledger_0_PV", "material": "G4_AIR", "reason": "Geant4 world retains default region; no world-air deposition ledger or full energy closure is claimed"}]}
    if ring_case(request):
        base.update(producer_adapter="ring_cs137_v1", model_contract=model_contract, ring_source_sha256=ring.ring_source_hashes(),
                    probes=probes, analytic_volume_mm3=ring.reference_volume(model), native_geometry_wall_s=elapsed,
                    mounting_contract=scenario["mounting_contract"])
    return base


def file_inventory(directory):
    files = {}
    for path in directory.rglob("*"):
        local(path)
        if path.is_file():
            files[path.relative_to(directory).as_posix()] = digest(path)
    return files


def expected_preparation_files(request):
    files = PREP_FILES | {"portable-plan.json", "runtime/emlow-data.json", "runtime/runtime.json"}
    files |= {"resolved-instance.json"} if request["source_mode"] == GAMMA else {"scenario.json"}
    if ring_case(request):
        files.add("effective-model/model-contract.json")
        if request["detector"] == "GeRC02_Li50min":
            files.add("effective-model/GeRC02.yaml")
    return files


def prepare(request, output, windows_root, checked_plan):
    checked = validate_checked_plan(checked_plan, request, windows_root)
    h, cs, s, gamma, ring, models = helpers()
    request = checked["request"]
    output = local(output)
    require(not output.exists(), "output collision; preserve prior preparation")
    _, points, scenario, probes, source, plan = geometry_contract(request, checked["gamma_plan"])
    output.mkdir(parents=True)
    status = {"kind": s.KIND if request["source_mode"] == GAMMA else "portable_source_prepare_receipt_v1", "status": "failed",
              "stage": "geometry_preparation", "execution_contract": checked["execution_contract"], "portable_source_sha256": checked["portable_source_sha256"]}
    start = time.perf_counter()
    try:
        h.publish_json(output / "portable-plan.json", checked)
        runtime_data(output, checked["runtime"], request["source_mode"])
        model_contract = models.prepare(model_id(request), output / "effective-model") if ring_case(request) else None
        h.write_new(output / "canonical.gdml", h.gdml_text(points))
        h.write_new(output / "probe-points.txt", probe_text(probes))
        h.write_new(output / "parameters.txt", parameter_text(scenario, source, request["source_mode"] == GAMMA))
        h.write_new(output / ("resolved-instance.json" if plan else "scenario.json"), h.json_text(plan or scenario))
        inputs = file_inventory(output)
        validate_checked_plan(checked, request, windows_root)
        status["command"] = geometry_command(output)
        with (output / "geometry.log").open("x", encoding="utf-8") as log:
            t = time.perf_counter()
            result = subprocess.run(status["command"], stdout=log, stderr=subprocess.STDOUT, check=False, shell=False)
            status["native_geometry_wall_s"] = time.perf_counter() - t
        status["returncode"] = result.returncode
        require(type(result.returncode) is int and result.returncode == 0, "native geometry failed; preserve log/report")
        require(not re.search(DIAGNOSTIC, (output / "geometry.log").read_text(errors="replace"), re.I), "native geometry diagnostic failure")
        report = load(output / "geometry-report.json")
        validate_geometry(report, request, scenario, plan, probes)
        require((output / "geometry.gdml").is_file(), "native geometry missing")
        macro = s.source_macro(report, plan) if plan else cs.macro_text(report, request["primary_count"], source)
        h.write_new(output / "run.mac", macro)
        require(all(digest(output / ref) == sha for ref, sha in inputs.items()), "prepared input changed during geometry")
        validate_checked_plan(checked, request, windows_root)
        if model_contract:
            models.validate(model_contract)
        recheck_runtime_data(load(output / "runtime/runtime.json"), request["source_mode"])
        files = file_inventory(output)
        require(set(files) == expected_preparation_files(request), "unexpected fresh prepared file census")
        metadata = metadata_for(output, checked, report, model_contract, status["native_geometry_wall_s"], files)
        h.publish_json(output / "prepared.json", metadata)
        status["prepared_sha256"] = digest(output / "prepared.json")
        status["status"] = "complete"
        return metadata
    except Exception as error:
        status["error"] = str(error)
        raise
    finally:
        status["preparation_wall_s"] = time.perf_counter() - start
        h.publish_json(output / "prepare-receipt.json", status)


def read_prepared(directory, windows_root):
    """Paired reader: reconstruct semantic inputs, never call historical readers."""
    h, cs, s, gamma, ring, models = helpers()
    directory = local(directory)
    meta = load(directory / "prepared.json")
    checked = load(directory / "portable-plan.json")
    checked = validate_checked_plan(checked, checked["request"], windows_root)
    request = checked["request"]
    validate_execution_binding(meta.get("execution_contract"), meta.get("portable_source_sha256"), checked["execution_contract"], checked["portable_source_sha256"])
    files = {**meta.get("files_sha256", {}), **meta.get("portable_files_sha256", {})}
    require(type(meta.get("files_sha256")) is dict and set(files) == expected_preparation_files(request), "preparation inventory/census changed")
    pins = {ref: digest(safe_path(directory, ref, True)) for ref in expected_preparation_files(request)}
    exact(files, pins, "prepared bytes changed")
    _, points, scenario, probes, source, plan = geometry_contract(request, checked["gamma_plan"])
    report = load(directory / "geometry-report.json")
    validate_geometry(report, request, scenario, plan, probes)
    exact((directory / "canonical.gdml").read_text(encoding="utf-8"), h.gdml_text(points), "rehashed canonical geometry changed")
    exact((directory / "probe-points.txt").read_text(encoding="utf-8"), probe_text(probes), "rehashed probes changed")
    exact((directory / "parameters.txt").read_text(encoding="utf-8"), parameter_text(scenario, source, request["source_mode"] == GAMMA), "rehashed native parameters changed")
    exact(load(directory / ("resolved-instance.json" if plan else "scenario.json")), plan or scenario, "rehashed source/pose/resolved scenario changed")
    expected_macro = s.source_macro(report, plan) if plan else cs.macro_text(report, request["primary_count"], source)
    exact((directory / "run.mac").read_text(encoding="utf-8"), expected_macro, "rehashed macro/count/seed/clock changed")
    model_contract = None
    if ring_case(request):
        model_contract = models.validate(load(directory / "effective-model/model-contract.json"))
        require(model_contract["variant_id"] == request["detector"], "effective model variant mismatch")
        expected_ref = (directory / "effective-model/GeRC02.yaml").relative_to(ROOT).as_posix() if request["detector"] == "GeRC02_Li50min" else "models/KMRC01_candidate.yaml"
        require(model_contract["effective_model_ref"] == expected_ref, "effective model belongs to a different run")
    timing = meta.get("native_geometry_wall_s", 0)
    require(type(timing) in (int, float) and math.isfinite(timing) and timing >= 0, "invalid geometry timing")
    expected = metadata_for(directory, checked, report, model_contract, timing, pins)
    exact(meta, expected, "rehashed prepared semantics/provenance/legacy source maps changed")
    receipt = load(directory / "prepare-receipt.json")
    require(set(receipt) == {"kind", "status", "stage", "execution_contract", "portable_source_sha256", "command", "native_geometry_wall_s", "returncode", "prepared_sha256", "preparation_wall_s"}, "unsupported completed preparation receipt")
    exact([receipt["kind"], receipt["stage"]], [s.KIND if request["source_mode"] == GAMMA else "portable_source_prepare_receipt_v1", "geometry_preparation"], "preparation receipt kind/stage changed")
    require(receipt["status"] == "complete" and type(receipt["returncode"]) is int and receipt["returncode"] == 0,
            "missing matching complete preparation")
    require(receipt["prepared_sha256"] == digest(directory / "prepared.json"), "preparation receipt binding changed")
    exact(receipt["command"], geometry_command(directory), "geometry command/exporter binding changed")
    exact(receipt["native_geometry_wall_s"], timing, "geometry receipt/timing changed")
    require(type(receipt["preparation_wall_s"]) in (int,float) and math.isfinite(receipt["preparation_wall_s"]) and receipt["preparation_wall_s"] >= 0, "invalid preparation time")
    validate_execution_binding(receipt["execution_contract"], receipt["portable_source_sha256"], checked["execution_contract"], checked["portable_source_sha256"])
    require(not re.search(DIAGNOSTIC, (directory / "geometry.log").read_text(errors="replace"), re.I), "retained geometry diagnostic failure")
    runtime = load(directory / "runtime/runtime.json")
    exact(runtime["identity"], checked["runtime"], "prepared runtime admission changed")
    recheck_runtime_data(runtime, request["source_mode"])
    pins.update({"prepared.json": digest(directory / "prepared.json"), "prepare-receipt.json": digest(directory / "prepare-receipt.json")})
    return directory, meta, checked, runtime, pins


def recheck_prepared_pins(directory, pins):
    for ref, sha in pins.items():
        require(digest(safe_path(directory, ref, True)) == sha, "stage input changed: " + ref)


def actual_probe(raw, meta, request):
    _, cs, _, gamma, *_ = helpers()
    return gamma.validate_actual_probe(raw, meta) if request["source_mode"] == GAMMA else cs.validate_actual_probe(raw, meta)


def run(directory, windows_root):
    h, *_ = helpers()
    directory, meta, checked, runtime, pins = read_prepared(directory, windows_root)
    request = checked["request"]
    require(set(file_inventory(directory)) == set(pins), "run requires fresh complete preparation; preserve prior attempt")
    receipt = {"kind": "scenario_gamma_transport_run_v1" if request["source_mode"] == GAMMA else "portable_cs137_transport_run_v1",
               "status": "failed", "prepared_sha256": pins["prepared.json"], "command": command(request),
               "runtime": runtime, "execution_contract": checked["execution_contract"], "portable_source_sha256": checked["portable_source_sha256"],
               "transport_source_sha256": helpers()[3].producer_hashes() if request["source_mode"] == GAMMA else meta["source_sha256"]}
    start = time.perf_counter()
    try:
        recheck_prepared_pins(directory, pins)
        validate_checked_plan(checked, request, windows_root)
        with (directory / "run.log").open("x", encoding="utf-8") as log:
            t = time.perf_counter()
            result = subprocess.run(receipt["command"], cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=False, shell=False)
            receipt["remage_wall_s"] = time.perf_counter() - t
        receipt["returncode"] = result.returncode
        require(type(result.returncode) is int and result.returncode == 0, "radiation failed; preserve raw/log")
        require(not re.search(DIAGNOSTIC, (directory / "run.log").read_text(errors="replace"), re.I), "native radiation diagnostic failure")
        raw = local(directory / "truth.lh5")
        receipt["source_lh5_sha256"] = digest(raw)
        receipt["validation"] = actual_probe(raw, meta, request)
        require(digest(raw) == receipt["source_lh5_sha256"], "raw LH5 changed during validation")
        receipt["data_recheck_wall_s"] = recheck_runtime_data(runtime, request["source_mode"])
        validate_checked_plan(checked, request, windows_root)
        recheck_prepared_pins(directory, pins)
        receipt["status"] = "complete"
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        receipt["total_wall_s"] = time.perf_counter() - start
        h.publish_json(directory / "run.json", receipt)
    return receipt


def read_complete_run(directory, windows_root, *, with_stream=False):
    directory, meta, checked, runtime, pins = read_prepared(directory, windows_root)
    request = checked["request"]
    receipt = load(directory / "run.json")
    require(set(receipt) == {"kind", "status", "prepared_sha256", "command", "runtime", "execution_contract", "portable_source_sha256",
                            "transport_source_sha256", "remage_wall_s", "returncode", "source_lh5_sha256", "validation", "data_recheck_wall_s", "total_wall_s"}, "unsupported complete run keys")
    expected_kind = "scenario_gamma_transport_run_v1" if request["source_mode"] == GAMMA else "portable_cs137_transport_run_v1"
    exact([receipt["kind"], receipt["status"], receipt["returncode"], receipt["prepared_sha256"]],
          [expected_kind, "complete", 0, pins["prepared.json"]], "run incomplete/unpaired")
    exact(receipt["command"], command(request), "run command/seed/thread changed")
    exact(receipt["runtime"], runtime, "run runtime changed")
    for key in ("remage_wall_s", "data_recheck_wall_s", "total_wall_s"):
        require(type(receipt[key]) in (int, float) and math.isfinite(receipt[key]) and receipt[key] >= 0, "invalid run timing")
    expected_sources = helpers()[3].producer_hashes() if request["source_mode"] == GAMMA else meta["source_sha256"]
    exact(receipt["transport_source_sha256"], expected_sources, "run producer source binding changed")
    validate_execution_binding(receipt["execution_contract"], receipt["portable_source_sha256"], checked["execution_contract"], checked["portable_source_sha256"])
    require(not re.search(DIAGNOSTIC, (directory / "run.log").read_text(errors="replace"), re.I), "saved run has diagnostic failure")
    require(digest(directory / "truth.lh5") == receipt["source_lh5_sha256"], "raw LH5 changed")
    exact(actual_probe(directory / "truth.lh5", meta, request), receipt["validation"], "rehashed raw run census changed")
    expected_files = set(pins) | {"run.json", "run.log", "truth.lh5"}
    actual_files = set(file_inventory(directory))
    if with_stream:
        actual_files = {ref for ref in actual_files if not ref.startswith("stream/")}
    require(actual_files == expected_files, "extraction requires exact completed run census; preserve partial derivative")
    pins.update({"run.json": digest(directory / "run.json"), "run.log": digest(directory / "run.log"), "truth.lh5": receipt["source_lh5_sha256"]})
    return directory, meta, checked, runtime, pins, receipt


def raw_metadata(raw, meta, request):
    """Delegate table/UID interpretation to the frozen raw readers."""
    import h5py
    _, cs, _, gamma, *_ = helpers()
    with h5py.File(raw, "r") as source:
        names = ("vtx", "particles", "tracks", "processes", *meta["material_tables"])
        tables = {key: gamma.table_descriptor(source[key]) if request["source_mode"] == GAMMA else
                  {"rows": len(next(iter(source[key].values()))), "columns": {name: {"dtype": str(ds.dtype), "units": cs.scalar(ds.attrs.get("units", ""))} for name, ds in source[key].items()}} for key in names}
        origins = None
        if request["source_mode"] == GAMMA:
            tables["detector_origins"] = gamma.table_descriptor(source["detector_origins"])
            origins = gamma.detector_origins(source, meta)
        return tables, origins, list(cs.table_rows(source["processes"])), cs.step_aliases(source, meta["material_tables"])


def validate_stream_events(directory, meta, request, chunks):
    """Compare all saved records with the unchanged raw iterator, including zeros."""
    _, cs, _, gamma, *_ = helpers()
    raw_events = iter(gamma.iter_events(directory / "truth.lh5", meta) if request["source_mode"] == GAMMA else cs.iter_decays(directory / "truth.lh5", meta))
    expected, seen = 0, set()
    for chunk in chunks:
        first_key = "first_initial_primary_id" if request["source_mode"] == GAMMA else "first_global_decay_id"
        require(type(chunk) is dict and set(chunk) == {"file", "count", first_key, "sha256"}, "unsupported stream chunk keys")
        name = safe_ref(chunk["file"])
        require("/" not in name and name.endswith(".jsonl") and name not in seen, "foreign/repeated stream chunk")
        require(type(chunk["count"]) is int and 1 <= chunk["count"] <= 100 and type(chunk[first_key]) is int and chunk[first_key] == expected, "stream chunk census changed")
        if request["source_mode"] == GAMMA:
            require(name == "events-00000000.jsonl" and chunk["count"] == 20 and expected == 0, "gamma chunk changed")
        else:
            require(name == f"decays-{expected:08d}.jsonl", "decay chunk name changed")
        path = safe_path(directory / "stream", name, True)
        require(digest(path) == chunk["sha256"], "saved stream bytes changed")
        rows = path.read_text(encoding="utf-8").splitlines()
        require(len(rows) == chunk["count"], "saved stream lost/added original primary")
        for line in rows:
            # Parsing uses the same duplicate/nonfinite-key protections as receipts.
            event = json.loads(line, object_pairs_hook=json_pairs, parse_constant=bad_constant, parse_float=finite_float)
            actual = next(raw_events, None)
            require(actual is not None, "saved stream exceeds raw primary census")
            exact(event, actual, "rehashed event/raw identity, group, delay or zero changed")
            expected += 1
        seen.add(name)
    require(expected == request["primary_count"] and next(raw_events, None) is None, "incomplete original stream census")
    return expected


def read_stream(directory, windows_root):
    directory, meta, checked, runtime, pins, run_receipt = read_complete_run(directory, windows_root, with_stream=True)
    request = checked["request"]
    manifest = load(safe_path(directory, "stream/manifest.json", True))
    chunks = manifest["chunks"]
    count = validate_stream_events(directory, meta, request, chunks)
    tables, origins, processes, aliases = raw_metadata(directory / "truth.lh5", meta, request)
    expected = stream_metadata(meta, checked, pins, chunks, count, tables, origins, processes, aliases)
    exact(manifest, expected, "rehashed stream/raw/source/units metadata changed")
    receipt = load(safe_path(directory, "stream/extract-receipt.json", True))
    require(set(receipt) == {"kind", "status", "run_sha256", "execution_contract", "portable_source_sha256", "manifest_sha256", "wall_s"}, "unsupported extraction receipt")
    exact([receipt["kind"], receipt["status"], receipt["run_sha256"], receipt["manifest_sha256"]],
          ["portable_source_extract_receipt_v1", "complete", pins["run.json"], digest(directory / "stream/manifest.json")], "extraction receipt incomplete/unpaired")
    validate_execution_binding(receipt["execution_contract"], receipt["portable_source_sha256"], checked["execution_contract"], checked["portable_source_sha256"])
    require(type(receipt["wall_s"]) in (int, float) and math.isfinite(receipt["wall_s"]) and receipt["wall_s"] >= 0, "invalid extraction timing")
    expected_files = {c["file"] for c in chunks} | {"manifest.json", "extract-receipt.json"}
    require(set(file_inventory(directory / "stream")) == expected_files, "incomplete/foreign stream file census")
    recheck_prepared_pins(directory, pins)
    return manifest


def extract(directory, windows_root, chunk_size=100):
    """Reuse iter_decays/write_chunks or iter_events; preserve every original ID."""
    h, cs, s, gamma, ring, models = helpers()
    directory, meta, checked, runtime, pins, run_receipt = read_complete_run(directory, windows_root)
    request = checked["request"]
    require(type(chunk_size) is int and 1 <= chunk_size <= 100, "chunk size must be 1..100")
    if request["source_mode"] == GAMMA:
        require(chunk_size == 100, "gamma retains one twenty-event chunk")
    destination = local(directory / "stream")
    require(not destination.exists(), "stream collision; preserve prior derivative")
    receipt = {"kind": "portable_source_extract_receipt_v1", "status": "failed", "run_sha256": pins["run.json"],
               "execution_contract": checked["execution_contract"], "portable_source_sha256": checked["portable_source_sha256"]}
    start = time.perf_counter()
    try:
        raw = directory / "truth.lh5"
        if request["source_mode"] == GAMMA:
            destination.mkdir()
            part = destination / "events-00000000.jsonl.partial"
            count = 0
            with part.open("x", encoding="utf-8", newline="\n") as stream:
                for event in gamma.iter_events(raw, meta):
                    require(event["event_id"] == event["initial_primary_id"] == count, "missing/duplicate gamma primary")
                    stream.write(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
                    count += 1
                stream.flush(); os.fsync(stream.fileno())
            require(count == 20, "incomplete gamma census")
            chunks = [{"file": "events-00000000.jsonl", "count": 20, "first_initial_primary_id": 0, "sha256": digest(part)}]
        else:
            chunks, count = cs.write_chunks(cs.iter_decays(raw, meta), destination, chunk_size)
            require(count == request["primary_count"], "incomplete original decay census")
        tables, origins, processes, aliases = raw_metadata(raw, meta, request)
        recheck_prepared_pins(directory, pins)
        validate_checked_plan(checked, request, windows_root)
        recheck_runtime_data(runtime, request["source_mode"])
        exact(actual_probe(raw, meta, request), run_receipt["validation"], "extracted census differs from recorded raw validation")
        manifest = stream_metadata(meta, checked, pins, chunks, count, tables, origins, processes, aliases)
        if request["source_mode"] == GAMMA:
            final = destination / chunks[0]["file"]
            os.link(part, final); part.unlink()
        h.publish_json(destination / "manifest.json", manifest)
        receipt["manifest_sha256"] = digest(destination / "manifest.json")
        receipt["status"] = "complete"
        return manifest
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        receipt["wall_s"] = time.perf_counter() - start
        # An extract failure before chunk creation still keeps a no-clobber failure receipt.
        if not destination.exists():
            destination.mkdir()
        h.publish_json(destination / "extract-receipt.json", receipt)


def stream_metadata(meta, checked, pins, chunks, count, tables, origins, processes, aliases):
    h, cs, s, gamma, ring, models = helpers()
    request = checked["request"]
    shared = {"status": "complete", "primary_count": count, "model_id": meta["model_id"],
              "source_lh5": "../truth.lh5", "source_lh5_sha256": pins["truth.lh5"], "prepared_sha256": pins["prepared.json"], "run_sha256": pins["run.json"],
              "coordinate_transform": meta["coordinate_transform"], "chunks": chunks, "processes": processes, "raw_tables": tables, "uid_aliases": aliases,
              "units": {"energy": "keV", "length": "mm", "time": "ns"}, "raw_track_energy_unit": "MeV", "raw_position_unit": "m",
              "unscored_volumes": meta["unscored_volumes"], "execution_contract": checked["execution_contract"], "portable_source_sha256": checked["portable_source_sha256"]}
    if request["source_mode"] == GAMMA:
        return {**shared, "kind": gamma.KIND, "schema_version": 1, "initial_primary_id_range": [0, 19], "source_count_unit": "initial synthetic gamma primaries",
                "assets": meta["assets"], "source_position_global_mm": meta["source_position_global_mm"], "seed": 26092631, "threads": 1,
                "physics": {"EM": "Livermore", "default_production_cut_mm": 0.1, "sensitive_production_cut_mm": 0.01},
                "stored_temperature_K": meta["assets"]["detector"]["temperature_K"], "stored_contacts": meta["assets"]["detector"]["contacts"], "readout_contact_id": 1,
                "transport_source_sha256": gamma.producer_hashes(), "prepared_source_sha256": meta["source_sha256"],
                "detector_origins": origins, "material_tables": meta["material_tables"], "clock_policy": "synthetic_primary_time_zero", "normalization": meta["assets"]["source"]["normalization"],
                "ledger": {"kind": "recorded-only", "full_energy_closure": None, "activity_Bq": None,
                    "limitations": ["unscored world/escape energy", "births and scored STEP chords are not full trajectories", "20 primaries, low statistics", "nominal geometry, not as-built"]},
                "geometry_unknowns": meta["unknowns"], "omitted_hardware": meta["omitted"],
                "stages": {"transport": "transport_complete", "charge": "charge_not_executed", "readout": "readout_not_executed"}}
    manifest = {**shared, "kind": cs.KIND, "global_decay_id_range": [0, count - 1], "model_sha256": meta["model_sha256"], "source_sha256": meta["source_sha256"],
                "config_sha256": meta["files_sha256"]["scenario.json"], "geometry_sha256": meta["files_sha256"]["geometry.gdml"], "macro_sha256": meta["files_sha256"]["run.mac"],
                "grouping_policy": meta["grouping_policy"], "clock_policy": meta["clock_policy"], "decay_photon_line_window_keV": meta["decay_photon_line_window_keV"],
                "ledger": {"kind": "recorded-only", "full_energy_closure": None,
                    "missing_closure": ["world-air deposition (unscored default region)", "terminal escape energy", "neutrino escape balance", "complete decay/recoil accounting"],
                    "passive_raw_rows": "hashed truth.lh5; event material sums in JSONL"}}
    if ring_case(request):
        manifest.update(producer_adapter="ring_cs137_v1", ring_source_sha256=meta["ring_source_sha256"], model_contract=meta["model_contract"], mounting_contract=meta["mounting_contract"])
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build-exporter")
    build.add_argument("--windows-root", required=True)
    for name in ("check", "prepare"):
        item = sub.add_parser(name)
        if name == "check":
            selection = item.add_mutually_exclusive_group(required=True)
            selection.add_argument("--request-json")
            selection.add_argument("--directory")
            item.add_argument("--stage", choices=("geometry", "radiation", "event_ledger"))
        else:
            item.add_argument("--request", required=True)
        item.add_argument("--windows-root", required=True)
        if name == "prepare":
            item.add_argument("--checked-plan", required=True)
            item.add_argument("--output", required=True)
    for name in ("run", "extract"):
        item = sub.add_parser(name)
        item.add_argument("--directory", required=True)
        item.add_argument("--windows-root", required=True)
    args = parser.parse_args()
    if args.command == "build-exporter":
        value = build_exporter(args.windows_root)
    elif args.command == "check":
        if args.request_json:
            require(args.stage is None, "stage is only for saved-directory checking")
            value = check(json.loads(args.request_json, object_pairs_hook=json_pairs, parse_constant=bad_constant, parse_float=finite_float), args.windows_root)
        else:
            require(args.stage is not None, "saved directory checking requires a stage")
            reader = {"geometry": read_prepared, "radiation": read_complete_run, "event_ledger": read_stream}[args.stage]
            result = reader(args.directory, args.windows_root)
            value = result[1] if args.stage in ("geometry", "radiation") else result
    elif args.command == "prepare":
        value = prepare(load(safe_path(ROOT, args.request, True)), args.output, args.windows_root, load(local(args.checked_plan)))
    else:
        value = run(args.directory, args.windows_root) if args.command == "run" else extract(args.directory, args.windows_root)
    print(text(value), end="")


if __name__ == "__main__":
    main()
