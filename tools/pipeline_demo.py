"""Run the locked bare-detector pipeline, or export a verified offline showcase.

Python 3.10+ standard library only. No installs, caches, or supervisor state needed.
Public API: validate_export(directory) verifies the two showcase files without
running calculations; export_run(input, output) additionally checks original data.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath
import platform
import re
import shutil
import stat
import subprocess
import sys
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("AK02", "SAP22")
STAGES = ("prepare", "transport", "extract", "charge", "readout")
TEMPLATE = "tools/pipeline_explorer.html"
TOKEN = "__PIPELINE_DATA_JSON__"
PRESETS = {"quick": (10, 662), "gamma-662": (100, 662), "gamma-59": (100, 59.5)}
MAX_DEMO_ENERGY_KEV = 10000  # Explicit workload bound, not a validated physics range.
BASELINE_CONFIG = "simulation/readout_demo.json"
BASELINE_CONFIG_SHA256 = "33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e"
RUN_CONFIG = "readout-config.json"
PUBLIC_ENCODING = "json-compact-sorted-ascii-v1"
CHILD_THREAD_ENV = {"OPENBLAS_NUM_THREADS": "1", "OMP_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
REFERENCES = [
    {"title": "ORTEC 671 architecture (not this synthetic transfer function)",
     "url": "https://www.ortec-online.com/products/electronic-instruments/amplifiers/671"},
    {"title": "ASPEC-927 pulse-height ADC architecture",
     "url": "https://www.ortec-online.com/products/electronic-instruments/multi-channel-analyzers/basic-analog/aspec-927"},
    {"title": "CR-RC shaping and pole-zero compensation",
     "url": "https://indico.cern.ch/event/299180/contributions/1659568/"},
]
LIMITATIONS = [
    "Synthetic monoenergetic side-on photons in bare canonical geometry; no full isotope decay, cryostat, source encapsulation or absolute efficiency claim.",
    "Explicit 77 K override, canonical AK02 +500 V / SAP22 +700 V biases. SAP22's original ADL temperature parametrization is unchanged.",
    "AK02 is primary; SAP22 is a differently shaped non-Li cross-check, not a matched experimental control.",
    "Li-region collection efficiency and production convergence remain unresolved. stopped_without_contact is retained and is not a diagnosis of physical trapping.",
    "Synthetic charge-injection calibration, not hardware calibration. No noise, Fano fluctuations or cross-primary pileup; isolated event electronics reset.",
    "Numerically sampled analog signals followed by a peak ADC; the analog time grid is not waveform ADC acquisition.",
    "Any negative cumulative charge, however tiny, is rejected as negative_input: a conservative supported-waveform restriction, not a general polarity classifier. Signed charge and voltages are retained without rectification.",
    "Prepared contour and existing handoff/replay checks are used; this demo is not a new independent volume validation or as-built apparatus.",
    "Only measured spectra remain available; these examples make no measured-waveform comparison.",
]


def require(ok, message):
    if not ok:
        raise ValueError(message)


def json_text(value):
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=True, allow_nan=False) + "\n"


def public_json_text(value):
    """Lossless public encoding; raw artifacts and checksum identities stay pretty."""
    return json.dumps(value, sort_keys=True, ensure_ascii=True, allow_nan=False, separators=(",", ":")) + "\n"


def load_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def finite_float(token):
        value = float(token)
        require(math.isfinite(value), "nonfinite JSON: " + token)
        return value
    return json.loads(Path(path).read_text(encoding="utf-8"), object_pairs_hook=unique, parse_float=finite_float,
                      parse_constant=lambda x: require(False, "nonfinite JSON: " + x))


def digest(value):
    return hashlib.sha256(json_text(value).encode("utf-8")).hexdigest()


def sha256(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def no_links(path):
    """lstat's reparse flag catches Windows junctions on Python 3.10 too."""
    path = Path(path)
    for part in (path, *path.parents):
        try:
            info = part.lstat()
        except FileNotFoundError:
            continue
        require(not stat.S_ISLNK(info.st_mode) and not
                (getattr(info, "st_file_attributes", 0) & 0x400),
                "symlink/junction/reparse path refused")
    return path


def local_path(value, *, new=False):
    path = Path(value)
    if not path.is_absolute():
        path = ROOT / path
    path = Path(os.path.abspath(path))
    base = ROOT / ".local"
    require(path != base and path.is_relative_to(base), "path must be below project .local")
    no_links(path)
    require(path.resolve() == path, "resolved path differs from requested path")
    if new:
        require(not path.exists(), "output already exists; choose a new directory")
    return path


def relative_file(base, name):
    require(isinstance(name, str) and "\\" not in name, "invalid inventory path")
    p = PurePosixPath(name)
    require(not p.is_absolute() and p.parts and all(x not in (".", "..") for x in p.parts)
            and ":" not in name and str(p) == name, "unsafe inventory path")
    return no_links(base.joinpath(*p.parts))


def inventory(directory):
    """Every regular artifact including local logs; root run.json is excluded only."""
    result = {}
    for current, dirs, files in os.walk(directory, followlinks=False):
        for name in sorted(dirs + files):
            no_links(Path(current) / name)
        for name in sorted(files):
            p = Path(current) / name
            rel = p.relative_to(directory).as_posix()
            if rel != "run.json":
                require(p.is_file(), "nonregular artifact")
                result[rel] = sha256(p)
    return dict(sorted(result.items()))


def source_inventory():
    names = ["tools/pipeline_demo.py", "transport/handoff.py", "transport/run.sh",
             "transport/pixi.toml", "transport/pixi.lock", "simulation/run.jl",
             "simulation/replay.jl", "simulation/readout.jl", "simulation/test_readout.jl", "simulation/readout_demo.json",
             "simulation/Project.toml", "simulation/Manifest.toml"]
    # run.jl verifies the complete small, versioned model distribution.
    names += [p.relative_to(ROOT).as_posix() for p in (ROOT / "models").rglob("*") if p.is_file()]
    return {name: sha256(relative_file(ROOT, name)) for name in sorted(names)}


def write_new(path, value):
    with no_links(path).open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(value)


def seal_manifest(manifest):
    manifest.pop("manifest_sha256", None)
    manifest["manifest_sha256"] = digest(manifest)


def check_seal(manifest, key):
    payload = {k: v for k, v in manifest.items() if k != key}
    require(manifest.get(key) == digest(payload), "manifest content checksum mismatch")


def portable_command(command, output, linux_root=None):
    replacements = [(str(output), "{RUN}"), (output.as_posix(), "{RUN}")]
    if linux_root:
        replacements += [(linux_root + "/" + output.relative_to(ROOT).as_posix(), "{RUN}"),
                         (linux_root, ".")]
    replacements += [(str(ROOT), "."), (ROOT.as_posix(), ".")]
    result = []
    for arg in map(str, command):
        for old, new in replacements:
            arg = arg.replace(old, new)
        result.append(arg.replace("\\", "/"))
    # Executable installation paths are private and not portable.
    result[0] = result[0].split("/")[-1]
    return result


def execute(manifest, output, model, stage, command, *, linux_root=None, capture=False):
    record = {"model_id": model, "stage": stage, "status": "running",
              "command": portable_command(command, output, linux_root), "cwd": "{ROOT}",
              "input_artifacts": inventory(output), "output_artifacts": {}}
    manifest["stages"].append(record)
    log = output / (model or "") / (stage + ".log")
    record["log"] = log.relative_to(output).as_posix()
    started = time.perf_counter()
    print(f"[{model or 'run'}] {stage}: starting", flush=True)
    try:
        child_env = dict(os.environ, **CHILD_THREAD_ENV)
        with log.open("xb") as stream:
            subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT,
                           check=True, shell=False, env=child_env)
        record["status"] = "complete"
        return log.read_text(encoding="utf-8", errors="replace").strip() if capture else None
    except BaseException as exc:
        record["status"] = "failed"
        record["error_type"] = type(exc).__name__
        if isinstance(exc, subprocess.CalledProcessError):
            record["returncode"] = exc.returncode
        raise
    finally:
        record["wall_seconds"] = time.perf_counter() - started
        print(f"[{model or 'run'}] {stage}: {record['status']} ({record['wall_seconds']:.2f} s)", flush=True)
        after = inventory(output)
        record["output_artifacts"] = {k: v for k, v in after.items()
                                      if record["input_artifacts"].get(k) != v}


def commands_for(model, output, events, seed, energy, julia, linux_root=None, threads=2):
    """Argument arrays: no shell quoting, owner paths, or command interpolation."""
    root = linux_root or ROOT.as_posix()
    transport = root + "/" + (output / model / "transport").relative_to(ROOT).as_posix()
    radiation = (["wsl.exe", "--distribution", "Ubuntu-24.04", "--exec"] if linux_root else [])
    radiation += ["bash", root + "/transport/run.sh", "python", "-B", root + "/transport/handoff.py"]
    base = [str(julia), "--startup-file=no", f"--threads={threads}", "--project=" + str(ROOT / "simulation")]
    local = output / model
    return [
        ("prepare", radiation + ["prepare", "--model", model, "--output", transport,
                                 "--events", str(events), "--seed", str(seed), "--energy-kev", str(energy)]),
        ("transport", radiation + ["run", "--directory", transport]),
        ("extract", radiation + ["extract", "--directory", transport]),
        ("charge", base + [str(ROOT / "simulation/replay.jl"), "--input", str(local / "transport/events.json"),
                            "--output", str(local / "charge"), "--max-events", str(events), "--temperature-k", "77"]),
        ("readout", base + [str(ROOT / "simulation/readout.jl"), "--input", str(local / "charge"),
                             "--truth", str(local / "transport/events.json"), "--config",
                             str(output / RUN_CONFIG), "--output", str(local / "readout")]),
    ]


def runtime_probe_result(log):
    prefix = "PIPELINE_RUNTIME_JSON="
    records = [line[len(prefix):] for line in log.splitlines() if line.startswith(prefix)]
    require(len(records) == 1, "independent Julia runtime probe record missing/duplicated")
    return json.loads(records[0])


def run_settings(events=None, seed=None, energy=None, model=None, preset="gamma-662", threads=None):
    require(isinstance(preset, str) and preset in PRESETS, "unsupported preset; choose quick, gamma-662 or gamma-59")
    overrides = {k: v for k, v in {"events": events, "seed": seed, "energy_keV": energy,
                                  "model": model, "threads": threads}.items() if v is not None}
    events = PRESETS[preset][0] if events is None else events
    energy = PRESETS[preset][1] if energy is None else energy
    seed = 260926 if seed is None else seed
    threads = 2 if threads is None else threads
    require(type(events) is int and 1 <= events <= 500, "events must be 1..500")
    require(type(seed) is int and 0 < seed < 2**31, "seed must be 1..2^31-1")
    require(finite(energy) and 0 < energy <= MAX_DEMO_ENERGY_KEV, "energy must be finite in (0, 10000] keV for this bounded demo")
    require(type(threads) is int and 1 <= threads <= 4, "threads must be 1..4")
    require(model is None or (isinstance(model, str) and model in MODELS), "unsupported model")
    return {"events_per_model": events, "seed": seed, "energy_keV": energy, "threads": threads,
            "preset": preset, "explicit_overrides": overrides, "temperature_K": 77, "device": "cpu",
            "child_thread_environment": dict(CHILD_THREAD_ENV)}


def validate_settings(manifest):
    settings = manifest["settings"]
    overrides = settings["explicit_overrides"]
    require(isinstance(overrides, dict) and set(overrides) <= {"events", "seed", "energy_keV", "model", "threads"},
            "unsupported explicit overrides")
    expected = run_settings(overrides.get("events"), overrides.get("seed"), overrides.get("energy_keV"),
                            overrides.get("model"), settings["preset"], overrides.get("threads"))
    require(json_text(settings) == json_text(expected), "effective run settings/overrides mismatch")
    require(manifest["models"] == ([overrides["model"]] if "model" in overrides else list(MODELS)), "model override mismatch")


def effective_readout_config(count):
    baseline = load_json(ROOT / BASELINE_CONFIG)
    require(sha256(ROOT / BASELINE_CONFIG) == BASELINE_CONFIG_SHA256, "frozen baseline readout config changed; review required")
    require(type(count) is int and 1 <= count <= 500, "events must be 1..500")
    effective = dict(baseline, expected_primary_count=count)
    binding = {"file": RUN_CONFIG, "baseline_file": BASELINE_CONFIG, "baseline_sha256": BASELINE_CONFIG_SHA256,
               "effective_sha256": digest(effective), "allowed_changed_fields": ["expected_primary_count"],
               "changed_fields": ["expected_primary_count"] if baseline["expected_primary_count"] != count else []}
    return effective, binding


def validate_run_config(directory, manifest):
    expected, binding = effective_readout_config(manifest["settings"]["events_per_model"])
    require(manifest.get("readout_config") == binding and manifest["sources"][BASELINE_CONFIG] == binding["baseline_sha256"],
            "readout config binding/allowlist mismatch")
    path = directory / RUN_CONFIG
    require(json_text(load_json(path)) == json_text(expected) and sha256(path) == binding["effective_sha256"],
            "run readout config may change only expected_primary_count")
    return expected


def run_pipeline(output, events=None, seed=None, energy=None, model=None, preset="gamma-662", threads=None):
    settings = run_settings(events, seed, energy, model, preset, threads)
    events, seed, energy, threads = (settings[k] for k in ("events_per_model", "seed", "energy_keV", "threads"))
    output = local_path(output, new=True)
    output.mkdir(parents=True, exist_ok=False)
    manifest = {"schema_version": 2, "kind": "hpge_pipeline_run", "run_id": uuid.uuid4().hex,
                "status": "running", "models": [model] if model else list(MODELS),
                "settings": settings,
                "driver_version": {"python": platform.python_version(), "os": sys.platform},
                "sources": {}, "stages": [], "artifacts": {}, "event_keys": []}
    started = time.perf_counter()
    phase = "preflight"
    print(f"[run] {preset}: {events} monoenergetic photons/model at {energy} keV; Julia threads={threads}; serial models", flush=True)
    try:
        manifest["sources"] = source_inventory()
        config, manifest["readout_config"] = effective_readout_config(events)
        write_new(output / RUN_CONFIG, json_text(config))
        julia = os.environ.get("JULIA_EXECUTABLE") or shutil.which("julia")
        require(bool(julia), "Julia missing: set JULIA_EXECUTABLE or add julia to PATH; no installation attempted")
        linux_root = None
        if os.name == "nt":
            phase = "wslpath"
            linux_root = execute(manifest, output, None, "wslpath",
                                 ["wsl.exe", "--distribution", "Ubuntu-24.04", "--exec", "wslpath", "-a", "-u", str(ROOT)],
                                 capture=True)
            require(linux_root.startswith("/") and "\n" not in linux_root, "wslpath did not return one absolute Linux path")
        phase = "julia_environment"
        probe = 'using JSON, SHA; println(); println("PIPELINE_RUNTIME_JSON=" * JSON.json(Dict("julia_version"=>string(VERSION), "json_version"=>string(Base.pkgversion(JSON)), "json_source_sha256"=>bytes2hex(sha256(read(pathof(JSON)))))))'
        manifest["runtime_environment"] = runtime_probe_result(execute(manifest, output, None, phase,
            [str(julia), "--startup-file=no", f"--threads={threads}", "--project=" + str(ROOT / "simulation"), "-e", probe], capture=True))
        for model_id in manifest["models"]:
            (output / model_id).mkdir()
            for phase, command in commands_for(model_id, output, events, seed, energy, julia, linux_root, threads):
                execute(manifest, output, model_id, phase, command, linux_root=linux_root)
                require(source_inventory() == manifest["sources"], "calculation inputs/sources changed during run")
            phase = "validate"
            checked = validate_model(output, model_id, manifest)
            identity = calibration_identity(checked)
            require(manifest.get("calibration_identity", identity) == identity, "calibration identity differs across models")
            manifest["calibration_identity"] = identity
            manifest["calibration_sha256"] = digest(identity)
            manifest["event_keys"] += [f"{manifest['run_id']}:{model_id}:{i}" for i in range(events)]
        manifest["status"] = "complete"
    except BaseException as exc:
        manifest.update(status="failed", failure={"stage": phase, "error_type": type(exc).__name__,
                                                 "message": str(exc).replace(str(ROOT), "{ROOT}")})
        raise
    finally:
        manifest["wall_seconds"] = time.perf_counter() - started
        manifest["artifacts"] = inventory(output)
        manifest["inventory_policy"] = "All regular run artifacts, including logs; only this root run.json is excluded. Sources are relative to project root."
        seal_manifest(manifest)
        write_new(output / "run.json", json_text(manifest))
        print(f"[run] {manifest['status']} ({manifest['wall_seconds']:.2f} s); logs and manifest in output root", flush=True)
    return manifest


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def close(a, b, label):
    require(finite(a) and finite(b) and math.isclose(a, b, rel_tol=1e-10, abs_tol=1e-8), label)


def census(events, count, label):
    require(isinstance(events, list) and len(events) == count and
            all(type(e.get("event_id")) is int for e in events) and
            [e["event_id"] for e in events] == list(range(count)), label + " missing/duplicate/reordered event IDs")


def validate_signals(path, reports, readout=None, eion=2.95):
    counts = [0] * len(reports)
    negative = [False] * len(reports)
    last_id = -1
    last_t = last_q = dt = None
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ["event_id", "time_since_primary_ns", "induced_equivalent_energy_keV"], "signals CSV schema mismatch")
        for row in reader:
            eid = int(row["event_id"])
            t, q = float(row["time_since_primary_ns"]), float(row["induced_equivalent_energy_keV"])
            require(finite(t) and finite(q) and 0 <= eid < len(reports), "invalid signal sample")
            if eid != last_id:
                if last_id >= 0:
                    close(last_q, reports[last_id]["final_induced_equivalent_energy_keV"], "signal final charge mismatch")
                    close(last_t, reports[last_id]["time_since_primary_end_ns"], "signal endpoint mismatch")
                require(eid == last_id + 1 and t == 0 and q == 0, "missing/mixed signal IDs or nonzero initial sample")
                last_id, dt = eid, None
            else:
                require(t > last_t, "signal times not increasing")
                if dt is None:
                    dt = t - last_t
                close(t - last_t, dt, "signal grid is nonuniform")
            negative[eid] |= q < 0
            if readout is not None:
                trace = readout[eid]["trace"]
                if t in trace["time_ns"]:
                    j = trace["time_ns"].index(t)
                    close(trace["induced_charge_fC"][j], q * 1000 / eion * 1.602176634e-4, "display charge differs from original sample")
                    current = 0 if t == 0 else (q - last_q) * 1000 / eion * 1.602176634e-1 / dt
                    close(trace["current_nA"][j], current, "display current differs from original bin")
            last_t, last_q = t, q
            counts[eid] += 1
    require(last_id == len(reports) - 1, "missing signal IDs")
    close(last_q, reports[-1]["final_induced_equivalent_energy_keV"], "signal final charge mismatch")
    close(last_t, reports[-1]["time_since_primary_end_ns"], "signal endpoint mismatch")
    require(all(n >= 2 and n == e["samples"] for n, e in zip(counts, reports)), "signal sample count mismatch")
    return negative


def endpoint_bits(flags):
    require(isinstance(flags, dict), "schema v1 requires flags DICT")
    endpoints = [e for s in flags["steps"] for e in s["endpoints"]]
    require(all(type(e["step_limit_reached"]) is bool for e in endpoints), "invalid endpoint step-limit flag")
    return {"has_step_limit": any(e["step_limit_reached"] for e in endpoints),
            "has_stopped_without_contact": any(e["status"] == "stopped_without_contact" for e in endpoints)}


def calibration_identity(model):
    # Canonical numbers make JSON 2 and 2.0 the same identity; never round coefficients.
    def canonical(value):
        if finite(value):
            return float(value)
        if isinstance(value, dict):
            return {k: canonical(v) for k, v in value.items()}
        if isinstance(value, list):
            return [canonical(v) for v in value]
        return value
    return canonical({k: model[k] for k in ("config", "ionisation_energy_eV", "time_step_ns", "calibration")})


def check_common_calibration(models, record):
    identity = calibration_identity(models[0])
    require(all(calibration_identity(m) == identity for m in models), "calibration identity differs across models")
    require(record.get("calibration_identity") == identity and record.get("calibration_sha256") == digest(identity),
            "canonical calibration hash mismatch")


def validate_provenance(base, model, charge, truth, readout, manifest):
    sources = manifest["sources"]
    expected = {key: sha256(base / name) for key, name in {
        "charge_run_sha256": "charge/run.json", "signals_sha256": "charge/signals.csv",
        "truth_sha256": "transport/events.json", "source_lh5_sha256": "transport/truth.lh5",
        "geometry_sha256": "transport/geometry.gdml", "macro_sha256": "transport/run.mac",
        "prepared_sha256": "transport/prepared.json", "transport_run_sha256": "transport/run.json"}.items()}
    expected.update({key: sources[name] for key, name in {
        "model_sha256": f"models/{model}.yaml", "model_catalog_sha256": "models/catalog.json",
        "readout_source_sha256": "simulation/readout.jl",
        "manifest_sha256": "simulation/Manifest.toml", "charge_manifest_sha256": "simulation/Manifest.toml",
        "test_source_sha256": "simulation/test_readout.jl"}.items()})
    expected["config_sha256"] = manifest["readout_config"]["effective_sha256"]
    runtime = manifest["runtime_environment"]
    require(set(runtime) == {"julia_version", "json_version", "json_source_sha256"} and
            re.fullmatch(r"[0-9a-f]{64}", runtime["json_source_sha256"]), "invalid independent runtime provenance")
    pinned = re.search(r'^julia_version\s*=\s*"([^"]+)"', (ROOT / "simulation/Manifest.toml").read_text(encoding="utf-8"), re.M)
    require(pinned is not None, "lockfile Julia version missing")
    expected["readout_environment"] = dict(runtime, project="simulation/Project.toml", manifest="simulation/Manifest.toml",
        project_sha256=sources["simulation/Project.toml"], manifest_sha256=sources["simulation/Manifest.toml"], pinned_julia_version=pinned.group(1))
    require(all(readout[k] == expected["readout_environment"][k] for k in ("julia_version", "json_version", "pinned_julia_version")), "readout runtime version mismatch")
    code = {n: sources["simulation/" + n] for n in ("run.jl", "replay.jl")}
    require(charge["source_code_sha256"] == code, "charge sourcecode hashes mismatch")
    require(charge["environment_manifest_sha256"] == sources["simulation/Manifest.toml"], "charge lock hash mismatch")
    require(charge["source_lh5_sha256"] == expected["source_lh5_sha256"], "charge raw source hash mismatch")
    for k in ("prepared_sha256", "run_sha256"):
        require(charge["source_provenance"][k] == truth["provenance"][k], "charge source provenance mismatch")
    expected["charge_source_sha256"] = code
    expected["charge_versions"] = {"julia": charge["julia_version"], "ssd": charge["ssd_version"]}
    expected["transport"] = {k: truth["provenance"][k] for k in ("seed", "versions", "extractor_versions", "lock_sha256")}
    require(expected["transport"]["lock_sha256"] == sources["transport/pixi.lock"], "transport lock hash mismatch")
    require(readout["provenance"] == expected, "readout provenance mismatch (artifact/source/config/lock/version)")


def event_summary(events):
    bits = [endpoint_bits(e["flags"]) for e in events]
    return {"primaries": len(events), "accepted": sum(e["accepted"] for e in events),
            "zero_deposit": sum(e["deposited_energy_keV"] == 0 for e in events),
            "below_threshold": sum(e["rejection_reason"] == "below_threshold" for e in events),
            "saturated": sum(e["peak_V"] >= 10 for e in events),
            "negative_input": sum(e["negative_input"] for e in events),
            "peak_at_window_end": sum(e["peak_at_window_end"] for e in events),
            "step_limit": sum(b["has_step_limit"] for b in bits),
            "stopped_without_contact": sum(b["has_stopped_without_contact"] for b in bits),
            "flagged": sum(any(b.values()) for b in bits),
            "charge_status_counts": {key: sum(e["charge_status"] == key for e in events)
                                     for key in sorted({e["charge_status"] for e in events})}}


def validate_model(directory, model, manifest):
    """Cross-stage ledgers and display traces; no inference from a good-looking plot."""
    base = directory / model
    prepared = load_json(base / "transport/prepared.json")
    truth = load_json(base / "transport/events.json")
    transport = load_json(base / "transport/run.json")
    charge = load_json(base / "charge/run.json")
    readout = load_json(base / "readout/run.json")
    count = manifest["settings"]["events_per_model"]
    for doc in (prepared, truth, charge, readout):
        require(doc["model_id"] == model, "model identity mismatch")
    model_hash = manifest["sources"][f"models/{model}.yaml"]
    require(all(d["model_sha256"] == model_hash for d in (prepared, truth, charge)), "model hash mismatch")
    require(transport["status"] == "complete" and charge["status"] in
            ("completed", "completed_with_transport_flags"), "incomplete transport/charge stage")
    require(readout.get("status") == "completed", "incomplete readout stage: explicit completed status required")
    require(readout["schema_version"] == 1 and isinstance(readout["config"], dict) and
            isinstance(readout["calibration"], dict) and readout["calibration"], "invalid readout schema/calibration")
    config = validate_run_config(directory, manifest)
    require(json_text(readout["config"]) == json_text(config), "readout config differs from recorded input")
    require(readout["unselected_event_ids"] == [], "readout omitted selected primaries")
    require(readout["units"] == {"time": "ns", "charge": "fC", "current": "nA", "voltage": "V", "energy": "keV"}, "readout unit mismatch")
    cal = readout["calibration"]
    for key in ("volts_per_keV", "adc_lsb_V", "energy_keV", "charge_C", "peak_V", "peak_time_ns",
                "ionisation_energy_eV", "time_step_ns", "adc_half_lsb_energy_keV"):
        require(finite(cal[key]) and cal[key] > 0, "invalid calibration coefficient: " + key)
    require(cal["method"] == "single delta-charge injection at t=0; sampled analog peak; fixed across events", "unknown calibration method")
    require(cal["adc_convention"] == "floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=10 V", "unknown ADC convention")
    close(cal["energy_keV"], readout["config"]["calibration_energy_keV"], "injection energy mismatch")
    require(math.isclose(cal["charge_C"], cal["energy_keV"] * 1000 / cal["ionisation_energy_eV"] * 1.602176634e-19,
                         rel_tol=1e-12, abs_tol=1e-30), "injection charge mismatch")
    close(cal["time_step_ns"], charge["time_step_ns"], "calibration/charge dt mismatch")
    close(cal["time_step_ns"], readout["time_step_ns"], "calibration/readout dt mismatch")
    close(cal["adc_half_lsb_energy_keV"], cal["adc_lsb_V"] / 2 / cal["volts_per_keV"], "calibration ADC error bound mismatch")
    close(cal["adc_lsb_V"], 10 / 16384, "peak ADC convention changed")
    close(cal["peak_V"] / cal["energy_keV"], cal["volts_per_keV"], "calibration slope mismatch")
    close(cal["ionisation_energy_eV"], charge["ionisation_energy_eV"], "calibration pair energy mismatch")
    for doc, name in ((truth, "truth"), (charge, "charge"), (readout, "readout")):
        census(doc["events"], count, name)
    require(prepared["primary_count"] == truth["primary_count"] == charge["primary_count"] ==
            charge["selected_primary_count"] == count and charge["unselected_event_ids"] == [], "selection count mismatch")
    require(prepared["seed"] == manifest["settings"]["seed"], "seed mismatch")
    close(prepared["energy_keV"], manifest["settings"]["energy_keV"], "primary energy mismatch")
    close(charge["effective_temperature_K"], 77, "temperature override mismatch")
    close(charge["ionisation_energy_eV"], 2.95, "unexpected SSD pair energy; review rather than override")
    expected_bias = [0, 500 if model == "AK02" else 700]
    require(sorted(charge["contact_potentials_V"]) == expected_bias == sorted(prepared["stored_contact_potentials_V"]), "canonical bias changed")
    require(truth["coordinate_transform"] == prepared["coordinate_transform"], "coordinate transform mismatch")
    require(charge["geometry"]["ssd_contour_matches"] is True, "SSD contour check missing")
    checks = [(charge["input_sha256"], "transport/events.json"),
              (truth["source_lh5_sha256"], "transport/truth.lh5"),
              (truth["geometry_sha256"], "transport/geometry.gdml"),
              (truth["macro_sha256"], "transport/run.mac"),
              (truth["provenance"]["prepared_sha256"], "transport/prepared.json"),
              (truth["provenance"]["run_sha256"], "transport/run.json"),
              (transport["prepared_sha256"], "transport/prepared.json"),
              (transport["source_lh5_sha256"], "transport/truth.lh5")]
    for expected, name in checks:
        require(sha256(base / name) == expected, "stage provenance hash mismatch: " + name)
    validate_provenance(base, model, charge, truth, readout, manifest)
    for name, expected in prepared["files_sha256"].items():
        require(sha256(relative_file(base / "transport", name)) == expected, "prepared artifact changed")
    negatives = validate_signals(base / "charge/signals.csv", charge["events"], readout["events"], charge["ionisation_energy_eV"])
    rows, public_events, energy_sum = [], [], 0.0
    for t, c, r in zip(truth["events"], charge["events"], readout["events"]):
        edep = math.fsum(s["energy_keV"] for s in t["steps"])
        require(0 <= edep <= prepared["energy_keV"] + 1e-6, "invalid event deposited energy")
        energy_sum += edep
        for step in t["steps"]:
            require(finite(step["energy_keV"]) and step["energy_keV"] >= 0 and
                    finite(step["time_ns"]) and step["time_ns"] >= t["primary_time_ns"], "invalid deposition ledger")
            require(len(step["position_mm"]) == 3 and all(finite(v) for v in step["position_mm"]), "invalid deposit position")
            rows.append(step["raw_row_index"])
        close(edep, c["deposited_energy_keV"], "truth/charge energy ledger mismatch")
        close(edep, r["deposited_energy_keV"], "truth/readout energy ledger mismatch")
        close(c["final_induced_equivalent_energy_keV"], r["final_induced_equivalent_energy_keV"], "charge/readout ledger mismatch")
        require(r["charge_status"] == c["status"], "charge status lost")
        require(type(r["accepted"]) is bool and isinstance(r["flags"], dict), "schema v1 requires flags DICT and boolean acceptance")
        require(r["flags"] == {"charge_status": c["status"], "steps":
                [{"raw_row_index": s["raw_row_index"], "endpoints": s["endpoints"]} for s in c["steps"]]}, "endpoint flags lost")
        bits = endpoint_bits(r["flags"])
        expected_status = "zero_deposit" if edep == 0 else "step_limit" if bits["has_step_limit"] else "stopped_without_contact" if bits["has_stopped_without_contact"] else "completed"
        require(c["status"] == expected_status, "aggregate charge status differs from endpoints")
        require(type(r["adc_code"]) is int and 0 <= r["adc_code"] < 16384, "invalid peak ADC code")
        require(finite(r["peak_V"]) and finite(r["peak_time_ns"]), "invalid analog peak")
        code = min(16383, max(0, math.floor(r["peak_V"] / cal["adc_lsb_V"])))
        require(code == r["adc_code"], "peak ADC code mismatch")
        # Current producer uses window_limited; expose its precise meaning publicly.
        window = r.get("peak_at_window_end", r.get("window_limited"))
        require(type(window) is bool and window == (r["peak_time_ns"] == r["readout_end_ns"]), "peak window flag mismatch")
        if "window_limited" in r:
            require(r["window_limited"] is window, "conflicting peak window flags")
        require(type(r["negative_input"]) is bool and r["negative_input"] == negatives[r["event_id"]], "negative cumulative charge flag mismatch")
        require(type(r["saturated"]) is bool and r["saturated"] == (r["peak_V"] >= 10), "saturation flag mismatch")
        reason = "negative_input" if r["negative_input"] else "saturated" if r["saturated"] else "peak_at_window_end" if window else "below_threshold" if r["peak_V"] < readout["config"]["threshold_V"] else None
        require(r["rejection_reason"] == reason and r["accepted"] == (reason is None), "ADC threshold/rejection mismatch")
        close(r["analog_energy_keV"], r["peak_V"] / cal["volts_per_keV"], "analog energy/calibration mismatch")
        close(r["adc_midpoint_V"], (code + .5) * cal["adc_lsb_V"], "ADC midpoint mismatch")
        require((r["accepted"] and finite(r["reconstructed_energy_keV"]) and r["rejection_reason"] is None) or
                (not r["accepted"] and r["reconstructed_energy_keV"] is None and isinstance(r["rejection_reason"], str)), "accepted/rejected energy inconsistency")
        if r["accepted"]:
            require(readout["config"]["threshold_V"] <= r["peak_V"] < 10, "accepted peak outside ADC/threshold range")
            close(r["reconstructed_energy_keV"], (code + .5) * cal["adc_lsb_V"] / cal["volts_per_keV"], "reconstructed energy/calibration mismatch")
        trace = r["trace"]
        times = trace["time_ns"]
        require(2 <= len(times) <= 600 and times[0] == 0 and all(b > a for a, b in zip(times, times[1:])), "invalid display time grid")
        for key in ("time_ns", "induced_charge_fC", "current_nA", "preamp_V", "shaped_V", "current_bin_start_ns", "current_bin_end_ns"):
            require(len(trace[key]) == len(times) and all(finite(v) for v in trace[key]), "invalid display trace: " + key)
        for j, time_ns in enumerate(times):
            close(trace["current_bin_end_ns"][j], time_ns, "current bin end mismatch")
            close(trace["current_bin_start_ns"][j], max(0, time_ns - cal["time_step_ns"]), "current bin start mismatch")
            if time_ns > r["charge_end_ns"]:
                require(trace["current_nA"][j] == 0, "tail current is not zero")
        close(r["charge_end_ns"], c["time_since_primary_end_ns"], "original charge window mismatch")
        require(r["charge_end_ns"] in times, "charge endpoint missing from trace")
        balance = r["current_balance"]
        require(all(finite(balance[k]) for k in ("integrated_current_C", "charge_change_C", "residual_C", "tolerance_C")) and
                balance["tolerance_C"] >= 0 and balance["passed"] is True and abs(balance["residual_C"]) <= balance["tolerance_C"], "current/charge balance failed")
        delta = c["final_induced_equivalent_energy_keV"] * 1000 / charge["ionisation_energy_eV"] * 1.602176634e-19
        for value in (balance["charge_change_C"], r["final_charge_C"]):
            require(math.isclose(value, delta, rel_tol=1e-10, abs_tol=1e-30), "current balance charge mismatch")
        require(math.isclose(balance["integrated_current_C"] - balance["charge_change_C"], balance["residual_C"],
                             rel_tol=1e-10, abs_tol=1e-30), "current balance residual mismatch")
        require(r["peak_time_ns"] in times, "exact peak sample absent from display trace")
        close(trace["shaped_V"][times.index(r["peak_time_ns"])], r["peak_V"], "display peak differs from exact peak")
        close(max(trace["shaped_V"]), r["peak_V"], "peak is not display maximum")
        close(trace["induced_charge_fC"][-1], c["final_induced_equivalent_energy_keV"] * 1e3 / charge["ionisation_energy_eV"] * 1.602176634e-4, "display final charge mismatch")
        require(times[-1] >= c["time_since_primary_end_ns"], "readout truncated charge signal")
        require(r["input_sample_count"] == c["samples"] and type(r["original_sample_count"]) is int and
                r["original_sample_count"] >= len(times), "readout sample census mismatch")
        close(times[-1], r["readout_end_ns"], "readout display endpoint missing")
        event = {key: r[key] for key in ("event_id", "deposited_energy_keV", "final_induced_equivalent_energy_keV",
                 "charge_status", "peak_V", "peak_time_ns", "adc_code", "reconstructed_energy_keV", "accepted", "rejection_reason", "flags", "trace")}
        event.update({key: r[key] for key in ("input_sample_count", "original_sample_count", "readout_end_ns",
                     "charge_end_ns", "tail_window_ns", "current_balance", "trace_preserves_all_current_runs",
                     "negative_input", "saturated", "analog_energy_keV", "adc_midpoint_V", "final_charge_C")})
        event.update(bits, peak_at_window_end=window)
        if "window_limited" in r:
            event["window_limited"] = r["window_limited"]
        event["event_key"] = f"{manifest['run_id']}:{model}:{r['event_id']}"
        event["primary_time_ns"] = t["primary_time_ns"]
        event["deposits"] = [{key: s[key] for key in ("raw_row_index", "energy_keV", "time_ns", "position_mm",
                             "global_position_m", "pre_position_mm", "post_position_mm", "track_id", "parent_track_id", "particle_pdg")} for s in t["steps"]]
        public_events.append(event)
    require(sorted(rows) == list(range(len(rows))) and all(type(r) is int for r in rows), "missing/duplicate deposition rows")
    close(energy_sum, truth["energy_sum_keV"], "total truth energy ledger mismatch")
    for name in ("events.csv", "spectrum.csv"):
        require((base / "readout" / name).is_file(), "missing readout artifact: " + name)
    summary = event_summary(public_events)
    expected_summary = {"primary_count": count, "selected_primary_count": count,
                        "accepted_count": summary["accepted"], "rejected_count": count - summary["accepted"],
                        "zero_deposit_count": summary["zero_deposit"], "transport_flagged_count": summary["flagged"],
                        "total_original_samples": sum(e["original_sample_count"] for e in public_events)}
    require(all(readout["summary"].get(k) == v for k, v in expected_summary.items()), "readout summary/selection mismatch")
    return {"model_id": model, "model_sha256": model_hash, "temperature_K": 77,
            "contact_potentials_V": charge["contact_potentials_V"], "ionisation_energy_eV": charge["ionisation_energy_eV"],
            "contour_rz_mm": prepared["contour_rz_mm"], "coordinate_transform": truth["coordinate_transform"],
            "config": readout["config"], "calibration": readout["calibration"],
            "events": public_events, "summary": summary, "readout_provenance": readout["provenance"],
            "readout_contact_id": readout["readout_contact_id"],
            "time_step_ns": readout["time_step_ns"], "polarity": readout["polarity"], "time_origin": readout["time_origin"],
            "supported_waveform_policy": readout["supported_waveform_policy"], "trace_current_convention": readout["trace_current_convention"],
            "potential_solve_timings": charge.get("timings", {}), "charge_wall_seconds": charge.get("runtime_seconds"),
            "versions": {"transport": truth["provenance"].get("versions", {}),
                         "julia": charge["julia_version"], "ssd": charge["ssd_version"], "readout_json": readout["json_version"]},
            "readout_limitations": readout["limitations"]}


def validate_run(directory):
    directory = local_path(directory)
    manifest = load_json(directory / "run.json")
    check_seal(manifest, "manifest_sha256")
    require(manifest.get("schema_version") == 2, "unsupported run schema; preserve archived runs and create a new run with this driver before export")
    require(manifest["kind"] == "hpge_pipeline_run" and manifest["status"] == "complete", "run is incomplete or unsupported")
    validate_settings(manifest)
    require(manifest["models"] in (["AK02"], ["SAP22"], list(MODELS)), "invalid model selection")
    require(manifest["artifacts"] == inventory(directory), "artifact inventory/hash mismatch")
    require(manifest["sources"] == source_inventory(), "input/source hash mismatch; preserve run and regenerate explicitly")
    validate_run_config(directory, manifest)
    require(runtime_probe_result((directory / "julia_environment.log").read_text(encoding="utf-8")) == manifest["runtime_environment"], "runtime probe/manifest mismatch")
    expected_stages = [(m, s) for m in manifest["models"] for s in STAGES]
    actual = [(r["model_id"], r["stage"]) for r in manifest["stages"] if r["model_id"] is not None]
    require(actual == expected_stages and all(r["status"] == "complete" for r in manifest["stages"]), "incomplete stage history")
    for stage in manifest["stages"]:
        command = stage["command"]
        if stage["stage"] in ("charge", "readout", "julia_environment"):
            require([v for v in command if v.startswith("--threads=")] == [f"--threads={manifest['settings']['threads']}"],
                    "Julia thread setting/command mismatch")
        if stage["stage"] == "readout":
            require(command.count("--config") == 1 and command[command.index("--config") + 1] == "{RUN}/" + RUN_CONFIG,
                    "readout must use the shared run config")
        for name, expected in stage["output_artifacts"].items():
            require(manifest["artifacts"].get(name) == expected, "stage artifact checksum mismatch")
    models = [validate_model(directory, m, manifest) for m in manifest["models"]]
    check_common_calibration(models, manifest)
    require(manifest["event_keys"] == [e["event_key"] for m in models for e in m["events"]], "composite event IDs mismatch")
    return manifest, models


def check_public(value):
    """Export is an allowlist, with a final guard against private paths in free text."""
    if isinstance(value, dict):
        for key, item in value.items():
            check_public(key)
            check_public(item)
    elif isinstance(value, list):
        for item in value:
            check_public(item)
    elif isinstance(value, str):
        require(not re.search(r"(?<![A-Za-z0-9])[A-Za-z]:[\\/]|file://|\\\\|/(?:Users|home|mnt|tmp|private|var)/", value, re.I), "private absolute path in public metadata")


def render_html(data, template=None):
    template = template if template is not None else (ROOT / TEMPLATE).read_text(encoding="utf-8")
    require(template.count(TOKEN) == 1, "HTML template placeholder count mismatch")
    # Escaping '<' also defeats case-insensitive closing-script sequences and HTML comments.
    embedded = public_json_text(data).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace(TOKEN, embedded)


def export_run(directory, output):
    output = local_path(output, new=True)
    manifest, models = validate_run(directory)
    data = {"schema_version": 2, "kind": "hpge_pipeline_showcase", "run_id": manifest["run_id"],
            "root_manifest_sha256": manifest["manifest_sha256"], "settings": manifest["settings"],
            "models": models, "limitations": LIMITATIONS, "references": REFERENCES,
            "calibration_identity": manifest["calibration_identity"], "calibration_sha256": manifest["calibration_sha256"],
            "readout_config": manifest["readout_config"],
            "provenance": {"sources": manifest["sources"], "artifacts": manifest["artifacts"],
                           "runtime_environment": manifest["runtime_environment"],
                           "driver_version": manifest["driver_version"], "wall_seconds": manifest["wall_seconds"],
                           "stages": [{k: r[k] for k in ("model_id", "stage", "status", "command", "wall_seconds")} for r in manifest["stages"]]},
            "export": {"files": ["data.json", "pipeline.html"], "encoding": PUBLIC_ENCODING, "template_sha256": sha256(ROOT / TEMPLATE),
                       "integrity": "export_sha256 covers canonical data without itself; HTML must equal template rendered with this complete data. No self-reference."}}
    check_public(data)
    data["export_sha256"] = digest(data)
    html = render_html(data)
    output.mkdir(parents=True, exist_ok=False)
    write_new(output / "data.json", public_json_text(data))
    write_new(output / "pipeline.html", html)
    validate_export(output)
    return data


def validate_export(directory):
    """For build_site: verify portable two-file export; no raw data or computation.

    Returns parsed data or raises ValueError/OSError. The source run was verified
    at export time; this helper attests consistency, not numerical validation.
    """
    directory = no_links(Path(directory).absolute())
    require(sorted(p.name for p in directory.iterdir()) == ["data.json", "pipeline.html"], "showcase must contain exactly data.json and pipeline.html")
    data_path, html_path = no_links(directory / "data.json"), no_links(directory / "pipeline.html")
    data = load_json(data_path)
    check_seal(data, "export_sha256")
    require(data.get("schema_version") == 2 and data["kind"] == "hpge_pipeline_showcase", "unsupported showcase schema; create a new run/export with this driver; preserve archived exports")
    require(data["export"].get("encoding") == PUBLIC_ENCODING, "unsupported public JSON encoding")
    require(data["export"]["files"] == ["data.json", "pipeline.html"] and
            data["export"]["template_sha256"] == sha256(ROOT / TEMPLATE), "showcase template/inventory mismatch")
    check_public(data)
    require(data_path.read_bytes() == public_json_text(data).encode("utf-8"), "data.json differs from canonical compact export")
    require(html_path.read_bytes() == render_html(data).encode("utf-8"), "pipeline.html differs from verified export")
    require(TOKEN not in html_path.read_text(encoding="utf-8"), "unresolved HTML placeholder")
    check_common_calibration(data["models"], data)
    for model in data["models"]:
        census(model["events"], data["settings"]["events_per_model"], "public")
        require(model["summary"] == event_summary(model["events"]), "public summary/selection mismatch")
    return data


class UniqueOption(argparse.Action):
    """Reject repeated options instead of silently accepting the final value."""
    def __call__(self, parser, namespace, value, option_string=None):
        seen = getattr(namespace, "_seen_options", set())
        if self.dest in seen:
            parser.error("duplicate option: " + option_string)
        seen.add(self.dest)
        namespace._seen_options = seen
        setattr(namespace, self.dest, value)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="execute transport, SSD and readout in the existing locked environments")
    run.add_argument("--output", required=True, action=UniqueOption)
    run.add_argument("--preset", choices=PRESETS, default="gamma-662", action=UniqueOption,
                     help="monoenergetic test scenarios, not isotope sources or verified line energies: quick=10 at 662 keV; gamma-662=100 at 662; gamma-59=100 at 59.5")
    run.add_argument("--events", type=int, action=UniqueOption, help="override preset count: 1..500 photons per model")
    run.add_argument("--model", choices=MODELS, action=UniqueOption)
    run.add_argument("--seed", type=int, action=UniqueOption, help="default 260926")
    run.add_argument("--energy-kev", type=float, action=UniqueOption, help="monoenergetic photon energy in (0, 10000] keV; workload limit, not accuracy certification")
    run.add_argument("--threads", type=int, action=UniqueOption, help="Julia threads 1..4, default 2; child BLAS/OMP threads fixed at 1")
    export = sub.add_parser("export", help="validate a completed run and write the offline showcase")
    export.add_argument("--input", required=True)
    export.add_argument("--output", required=True)
    args = parser.parse_args(argv)
    try:
        if args.command == "run":
            result = run_pipeline(args.output, args.events, args.seed, args.energy_kev, args.model,
                                  preset=args.preset, threads=args.threads)
            print("Pipeline complete:", result["run_id"], "—", args.output)
        else:
            result = export_run(args.input, args.output)
            print("Showcase verified:", result["export_sha256"], "—", args.output)
    except (Exception, KeyboardInterrupt) as exc:
        print(f"Pipeline {args.command} failed ({type(exc).__name__}): {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
