"""Explicit read-only verification of the completed, registered ring campaign.

Historical control bytes are evidence, never executable code or launch authority.
The two public operations accept a detector name, not a caller-selected manifest,
campaign, phase, callback or runtime. Current prepare/run/start remain strict.
"""
from __future__ import annotations

from contextlib import ExitStack
import builtins
import hashlib
import importlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
from unittest.mock import patch

_ROOT = Path(__file__).resolve().parents[1]
_CAMPAIGN = ".local/ring-cs137-v1"
_BASIS = _CAMPAIGN + "/source-basis-v1/basis.json"
_BASIS_SHA = "c44f837c9330ee4c6a1b590668c4d6a4c44f663a9b8948f67534bf5dbf67d5a0"
_MODELS = ("GeRC02", "KMRC01_candidate")
_PORTABLE_LINE = b'JULIA = Path.home() / ".julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe"'
_SERIAL = threading.Lock()


def _require(ok, message):
    if not ok:
        raise ValueError(message)


def _path(path):
    result = Path(os.path.abspath(path))
    for item in (result, *result.parents):
        _require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(),
                 "Linked historical path refused")
    _require(result.resolve() == result, "Linked historical path refused")
    return result


def _relative(base, name):
    _require(type(name) is str and name and "\\" not in name and ":" not in name
             and not Path(name).is_absolute() and ".." not in Path(name).parts
             and Path(name).as_posix() == name, "Unsafe historical relative path")
    result = _path(base / name)
    _require(result.is_relative_to(_path(base)), "Historical path escapes its basis")
    return result


def _digest(path):
    result = hashlib.sha256()
    with _path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def _read(path):
    def invalid(value):
        raise ValueError("Nonfinite historical JSON: " + value)
    return json.loads(_path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid)


def _load_basis():
    root = _path(_ROOT)
    basis_path = _relative(root, _BASIS)
    _require(_digest(basis_path) == _BASIS_SHA, "Unregistered or changed historical basis")
    basis = _read(basis_path)
    _require(basis["kind"] == "completed_ring_source_basis_v1"
             and _path(basis["root"]) == root, "Historical campaign root differs")
    _require(len(basis["original_all44"]) == 44 and len(basis["original_all51"]) == 51
             and all(basis["original_all51"].get(k) == v for k, v in basis["original_all44"].items()),
             "Historical source inventories differ")
    _require(set(basis["archived_sources"]) == {"tools/ring_run.py"}, "Unknown archived source refused")
    record = basis["archived_sources"]["tools/ring_run.py"]
    _require(record["archive"] == "ring_run.py"
             and record["sha256"] == basis["original_all44"]["tools/ring_run.py"],
             "Historical archive authority differs")
    archive = _relative(basis_path.parent, record["archive"])
    _require(archive.stat().st_size == record["bytes"] and _digest(archive) == record["sha256"],
             "Historical archive bytes changed")
    original = archive.read_bytes()
    lines = [line for line in original.splitlines(keepends=True) if line.startswith(b"JULIA = ")]
    _require(len(lines) == 1, "Historical runtime declaration is ambiguous")
    line = lines[0]
    newline = b"\r\n" if line.endswith(b"\r\n") else b"\n"
    portable = original.replace(line, _PORTABLE_LINE + newline, 1)
    current = _relative(root, "tools/ring_run.py").read_bytes()
    _require(current in (original, portable), "Unapproved historical control-source change")
    for name, digest in basis["original_all51"].items():
        if name != "tools/ring_run.py":
            _require(_digest(_relative(root, name)) == digest, "Historical source changed: " + name)
    directory = _relative(root, _CAMPAIGN)
    _require(not any(directory.rglob("*.lock")), "Active or unresolved historical campaign lock")
    _require(len(basis["receipt_sha256"]) == 31, "Historical receipt inventory differs")
    for name, digest in basis["receipt_sha256"].items():
        _require(_digest(_relative(directory, name)) == digest, "Historical receipt changed: " + name)
    for name in ("production-GeRC02-COMPLETE.json", "km-pilot-COMPLETE.json", "km-production-COMPLETE.json"):
        terminal = _read(directory / name)
        _require(terminal.get("test_only") is not True
                 and terminal["status"] in ("completed", "completed_with_native_failures"),
                 "Historical operation requires a completed real terminal")
    for name in basis["receipt_sha256"]:
        if name.endswith("-supervisor-exit.json"):
            _require(_read(directory / name)["unresolved_child_intent"] is False,
                     "Historical supervisor has unresolved child intent")
    config = _read(directory / "config.json")
    km_config = _read(directory / "km-config.json")
    _require(config["source_sha256"] == basis["original_all44"]
             and km_config["source_sha256"] == basis["original_all51"], "Historical configuration inventory differs")
    _require(type(basis["supervisor_python"]) is str and Path(basis["supervisor_python"]).is_absolute(),
             "Invalid historical supervisor runtime")
    return basis, directory, archive, config


def _modules(publication):
    with patch.object(sys, "dont_write_bytecode", True):
        runner = importlib.import_module("ring_run")
        km = importlib.import_module("km_ring_run")
        provenance = importlib.import_module("ring_production")
        exporter = importlib.import_module("ring_publication") if publication else None
    _require(_path(runner.ROOT) == _path(_ROOT) and km.r is runner and provenance.r is runner
             and km.provenance is provenance
             and _path(km.CAMPAIGN) == _relative(_ROOT, _CAMPAIGN), "Historical verifier module root differs")
    if exporter is not None:
        _require(_path(exporter.ROOT) == _path(_ROOT) and callable(getattr(exporter, "_checked_inputs", None)),
                 "Publication requires its explicit saved-basis input adapter")
    return runner, km, provenance, exporter


def _blocked(*args, **kwargs):
    raise ValueError("Historical saved verification cannot write, launch or admit new execution")


def _guard(stack, runner, km, provenance, exporter, basis, archive, config):
    original_sha = runner.sha
    designated = _relative(_ROOT, "tools/ring_run.py")

    def historical_sha(path):
        return original_sha(archive if _path(path) == designated else path)

    stack.enter_context(patch.object(runner, "sha", historical_sha))
    stack.enter_context(patch.object(runner, "JULIA", Path(config["julia_executable"])))
    stack.enter_context(patch.object(sys, "executable", basis["supervisor_python"]))
    for module, names in ((runner, ("prepare", "run", "start", "execute", "model_pipeline", "main", "atomic")),
                          (km, ("prepare", "run", "start", "execute", "main")),
                          (provenance, ("start", "prepare", "run", "execute", "main")),
                          (exporter, ("write", "write_json", "freeze", "scene", "public_copy", "zip_files",
                                      "geometry_archive", "response", "build", "assemble", "main"))):
        if module is not None:
            for name in names:
                if hasattr(module, name):
                    stack.enter_context(patch.object(module, name, _blocked))
    for name in ("Popen", "run", "call", "check_call", "check_output", "getoutput", "getstatusoutput"):
        stack.enter_context(patch.object(subprocess, name, _blocked))
    for name in ("system", "startfile", "posix_spawn", "posix_spawnp", "spawnl", "spawnle", "spawnlp", "spawnlpe",
                 "spawnv", "spawnve", "spawnvp", "spawnvpe", "execv", "execve", "execl", "execle", "execvp", "execlp"):
        if hasattr(os, name):
            stack.enter_context(patch.object(os, name, _blocked))
    original_open = Path.open
    original_builtin_open = builtins.open
    original_io_open = io.open

    def readonly_open(path, mode="r", *args, **kwargs):
        _require(not any(flag in mode for flag in "wax+"), "Historical verification cannot open a writer")
        return original_open(path, mode, *args, **kwargs)

    stack.enter_context(patch.object(Path, "open", readonly_open))

    def readonly_file_open(original):
        def opened(file, mode="r", *args, **kwargs):
            _require(not any(flag in mode for flag in "wax+"), "Historical verification cannot open a writer")
            return original(file, mode, *args, **kwargs)
        return opened

    stack.enter_context(patch.object(builtins, "open", readonly_file_open(original_builtin_open)))
    stack.enter_context(patch.object(io, "open", readonly_file_open(original_io_open)))
    for name in ("mkdir", "touch", "unlink", "rename", "replace", "rmdir", "chmod", "write_bytes", "write_text"):
        stack.enter_context(patch.object(Path, name, _blocked))
    original_os_open = os.open

    def readonly_os_open(path, flags, *args, **kwargs):
        writes = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC | os.O_APPEND | os.O_EXCL
        _require(not flags & writes, "Historical verification cannot open a writer")
        return original_os_open(path, flags, *args, **kwargs)

    stack.enter_context(patch.object(os, "open", readonly_os_open))
    for name in ("write", "replace", "rename", "remove", "unlink", "mkdir", "makedirs", "rmdir",
                 "removedirs", "chmod", "link", "symlink", "truncate", "ftruncate"):
        stack.enter_context(patch.object(os, name, _blocked))


def _verify_ge(runner, provenance, directory):
    c = runner.config(directory)
    admitted = provenance.verify(directory, "GeRC02")
    _require(runner.equal(admitted, runner.read(directory / "production-GeRC02-admission.json")),
             "Saved Ge pilot admission changed")
    verified = runner.verify(directory, phase="production", model="GeRC02")
    result = verified["results"]["production10000/GeRC02"]
    complete = runner.read(directory / "production-GeRC02-COMPLETE.json")
    modeldir = directory / "production10000/GeRC02"
    commands = [runner.transport_command("prepare", "--model", "GeRC02", "--output", runner.ref(modeldir / "transport"),
                    "--exporter", runner.EXPORTER, "--events", "10000", "--seed", str(runner.SEEDS["GeRC02"])),
                runner.transport_command("run", "--directory", runner.ref(modeldir / "transport")),
                runner.transport_command("extract", "--directory", runner.ref(modeldir / "transport"), "--chunk-size", "100"),
                runner.response_command(c, modeldir, c["production_native_failure_policy"])]
    supervisors = set()
    for stage, argv in zip(("prepare", "transport", "extract", "response"), commands, strict=True):
        record = runner.read(directory / "stages" / ("production10000-GeRC02-" + stage + ".json"))
        _require(record.get("test_only") is not True and record["status"] == "complete" and record["exit_code"] == 0
                 and record["command_argv"] == argv and record["name"] == "production10000-GeRC02-" + stage
                 and record["source_sha256"] == c["source_sha256"] and type(record["child_pid"]) is int
                 and record["child_pid"] > 0 and type(record["supervisor_pid"]) is int and record["supervisor_pid"] > 0,
                 "Saved Ge production stage provenance differs")
        supervisors.add(record["supervisor_pid"])
    _require(len(supervisors) == 1, "Saved Ge production supervisors differ")
    launch = runner.read(directory / "production-GeRC02-launcher.json")
    exited = runner.read(directory / "production-GeRC02-supervisor-exit.json")
    argv = [sys.executable, "-u", "-B", str(runner.ROOT / "tools/ring_run.py"), "run", "--directory", str(directory),
            "--phase", "production", "--model", "GeRC02"]
    _require(launch["command_argv"] == argv and launch["output_root"] == runner.ref(directory)
             and launch["source_sha256"] == c["source_sha256"]
             and launch["pid"] == exited["pid"] == complete["supervisor_pid"] == supervisors.pop()
             and exited["unresolved_child_intent"] is False, "Saved Ge detached execution/exit differs")
    return {"status": verified["status"], "result": result, "new_science_stages": 0}


def _perform(model, publication):
    _require(model in _MODELS, "Unknown completed ring detector")
    _require(_SERIAL.acquire(blocking=False), "Historical saved verification is already active")
    try:
        basis, directory, archive, config = _load_basis()
        runner, km, provenance, exporter = _modules(publication)
        # Importing current modules must not change any registered input.
        _load_basis()
        with ExitStack() as stack:
            _guard(stack, runner, km, provenance, exporter, basis, archive, config)
            if publication:
                result = exporter._checked_inputs(model)
            elif model == "GeRC02":
                result = _verify_ge(runner, provenance, directory)
            else:
                result = km.verify(directory, phase="production")
        # Restore every global before checking the unchanged saved evidence again.
        _load_basis()
        if publication:
            return result
        return {**result, "verification_basis": "recorded_sources_v1", "basis_sha256": _BASIS_SHA,
                "original_source_sha256": basis["original_all44" if model == "GeRC02" else "original_all51"],
                "current_verifier_sha256": {name: _digest(_relative(_ROOT, "tools/" + name)) for name in
                    ("ring_saved_basis.py", "ring_run.py", "km_ring_run.py", "ring_production.py")},
                "historical_julia_binary_checked": True, "new_science_stages": 0}
    finally:
        _SERIAL.release()


def verify(model):
    """Verify registered completed production and its real pilot; never launch."""
    return _perform(model, publication=False)


def publication_inputs(model):
    """Return the maintained exporter's checked saved inputs under this basis."""
    return _perform(model, publication=True)
