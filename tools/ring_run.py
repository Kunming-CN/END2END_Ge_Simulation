"""One serial, detached ring Cs137 -> native SSD -> electronics campaign.

No installs, retries, geometry fitting, signal rectification or old-data reruns.
An interrupted/nonterminal stage requires inspection; this runner never overwrites it.
"""
import argparse
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
MODELS = ("GeRC02", "KMRC01_candidate")
SEEDS = {"GeRC02": 26100241, "KMRC01_candidate": 26100242}
JULIA = Path.home() / ".julia/juliaup/julia-1.13.0+0.x64.w64.mingw32/bin/julia.exe"
EXPORTER = ".local/m2a/cs137-build-v1/cryostat_export"
PROFILE = "simulation/native_readout_profile.json"
BASE_PRODUCER = ("cs137.py", "cryostat_export.cc", "cryostat_nominal.json", "handoff.py",
                 "cryostat-source.json", "pixi.toml", "pixi.lock", "CMakeLists.txt")
RING_PRODUCER = ("transport/ring_cs137.py", "transport/scenario_prepare.py", "tools/ring_model_contract.py")
NATIVE = ("native_response.jl", "native_stream.jl", "readout_profiles.jl", "native_li_example.jl",
          "readout.jl", "replay.jl", "run.jl", "readout_demo.json", "Project.toml", "Manifest.toml",
          "test_readout_profiles.jl", "test_native_stream.jl", "test_native_response.jl")
SOURCES = tuple("transport/" + x for x in BASE_PRODUCER) + RING_PRODUCER + tuple("simulation/" + x for x in NATIVE) + (
    "simulation/ring_stream.jl", "simulation/ring_response.jl", "simulation/test_ring_stream.jl", PROFILE, "models/catalog.json",
    "tools/ring_run.py", "tools/test_ring_run.py", EXPORTER)
KINDS = ("completed_provisional_native_response", "completed_with_native_failures")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def utc():
    return datetime.now(timezone.utc).isoformat()


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read(path):
    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid)


def equal(a, b):
    # Keep negative zero and numeric representations in copied scientific records.
    return json.dumps(a, sort_keys=True, allow_nan=False) == json.dumps(b, sort_keys=True, allow_nan=False)


def unlinked(path):
    path = Path(os.path.abspath(path))
    for item in (path, *path.parents):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "Linked path refused")
    require(path.resolve() == path, "Linked path refused")
    return path


def local(path):
    path = unlinked(path)
    base = unlinked(ROOT / ".local")
    require(path != base and path.is_relative_to(base), "Output must be below project .local")
    return path


def ref(path):
    path = unlinked(path)
    require(path.is_relative_to(ROOT), "Dependency escapes project")
    return path.relative_to(ROOT).as_posix()


def child(base, name):
    require(type(name) is str and name and "\\" not in name and not Path(name).is_absolute()
            and ".." not in Path(name).parts, "Unsafe relative artifact")
    result = local(Path(base) / name)
    require(result.is_relative_to(Path(base)), "Artifact escapes stage")
    return result


def atomic(path, value, fresh=False):
    path = local(path)
    require(not fresh or not path.exists(), "Receipt exists; preserve prior evidence")
    temporary = path.with_name(path.name + ".tmp-" + str(os.getpid()) + "-" + str(time.time_ns()))
    with temporary.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, indent=2, sort_keys=True, allow_nan=False)
        stream.write("\n"); stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def dependencies():
    inventory = set(SOURCES)
    catalog = read(ROOT / "models/catalog.json")
    for model in MODELS:
        entry = next(x for x in catalog["detectors"] if x["id"] == model)
        inventory.add("models/" + entry["model"])
        inventory.update("models/" + x for x in entry["dependencies"])
    upstream = read(ROOT / "transport/cryostat-source.json")
    inventory.update(".local/transport/LBNL/" + x["name"] for x in upstream["files"])
    result = {x: sha(unlinked(ROOT / x)) for x in sorted(inventory)}
    for item in upstream["files"]:
        require(result[".local/transport/LBNL/" + item["name"]] == item["sha256"], "Pinned upstream bytes changed")
    return result


def prepare(directory, threads=2, production_policy="record"):
    directory = local(directory)
    require(type(threads) is int and threads in (1, 2), "Julia threads must be one or two")
    require(production_policy in ("abort", "record"), "Invalid native failure policy")
    require(not directory.exists(), "Campaign exists; use verify and inspect, never overwrite")
    sources = dependencies()
    require(JULIA.is_file(), "Pinned native Julia executable missing")
    config = {"kind": "ring_fullchain_v1", "created_utc": utc(), "models": list(MODELS), "seeds": SEEDS,
              "pilot_count": 500, "production_count": 10000, "julia_threads": threads,
              "pilot_native_failure_policy": "abort", "production_native_failure_policy": production_policy,
              "native_parcels": 16, "native_seed": 2609261, "profile_ref": PROFILE,
              "exporter_ref": EXPORTER, "source_sha256": sources, "julia_executable": str(JULIA),
              "julia_executable_sha256": sha(JULIA), "new_field_cache_reuse_count": 0,
              "resource_bounds": {"models_serial": True, "stages_serial": True, "remage_threads": 1,
                                  "blas_threads": 1, "extract_chunk_primaries": 100,
                                  "max_samples_per_group": read(ROOT / "simulation/readout_demo.json")["max_samples_per_event"]},
              "scope": "Nominal engineering example; processing completion is not calibrated Li CCE or experimental validation",
              "resume_policy": "Only a fully verified terminal campaign is reusable; interrupted or failed stages require inspection"}
    directory.mkdir(parents=True)
    (directory / "stages").mkdir()
    atomic(directory / "config.json", config, fresh=True)
    (directory / "config.sha256").write_text(sha(directory / "config.json") + "\n", encoding="ascii")
    atomic(directory / "progress.json", {"status": "prepared", "created_utc": utc(), "new_science_stages": 0}, fresh=True)
    return config


def config(directory):
    directory = local(directory)
    c = read(directory / "config.json")
    require(sha(directory / "config.json") == (directory / "config.sha256").read_text().strip(), "Campaign configuration bytes changed")
    expected = {"kind": "ring_fullchain_v1", "models": list(MODELS), "seeds": SEEDS, "pilot_count": 500,
                "production_count": 10000, "pilot_native_failure_policy": "abort", "native_parcels": 16,
                "native_seed": 2609261, "profile_ref": PROFILE, "exporter_ref": EXPORTER,
                "new_field_cache_reuse_count": 0, "julia_executable": str(JULIA)}
    require(all(equal(c.get(k), v) for k, v in expected.items()), "Campaign settings changed")
    require(c["julia_threads"] in (1, 2) and c["production_native_failure_policy"] in ("abort", "record"), "Invalid resource/policy bounds")
    require(c["source_sha256"] == dependencies(), "Source changed after freeze; inspect without rerunning science")
    require(c["julia_executable_sha256"] == sha(JULIA), "Pinned Julia executable changed")
    return c


def linux_root():
    require(os.name == "nt" and str(ROOT).lower().startswith("c:\\"), "Run this existing-host entry on Windows")
    return "/mnt/c/" + ROOT.as_posix()[3:]


def transport_command(*args):
    # Fixed shell template only expands existing HOME; all arguments stay positional.
    template = 'exec "$HOME/.pixi/bin/pixi" run --locked --no-install --manifest-path transport/pixi.toml "$@"'
    return ["wsl.exe", "-d", "Ubuntu-24.04", "--cd", linux_root(), "--exec", "bash", "-c", template,
            "ring-run", "python", "-u", "-B",
            "transport/ring_cs137.py", *args]


def response_command(c, modeldir, policy):
    return [str(JULIA), "--startup-file=no", "--compiled-modules=existing", "--threads=" + str(c["julia_threads"]),
            "--project=simulation", "simulation/ring_response.jl", "--input", ref(modeldir / "transport/stream/manifest.json"),
            "--output", ref(modeldir / "response"), "--profile", PROFILE, "--parcels", "16", "--seed", "2609261",
            "--charge-csv", "examples", "--trace-examples", "4", "--native-failure-policy", policy]


def observed_rss(process):
    if os.name != "nt":
        return None
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("PageFaultCount", ctypes.c_ulong)] + [(x, ctypes.c_size_t) for x in
                    ("PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage", "QuotaPagedPoolUsage",
                     "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage", "PagefileUsage", "PeakPagefileUsage")]
    counters = Counters(); counters.cb = ctypes.sizeof(counters)
    function = ctypes.windll.psapi.GetProcessMemoryInfo
    function.argtypes = (ctypes.c_void_p, ctypes.c_void_p, ctypes.c_ulong)
    function.restype = ctypes.c_int
    if function(int(process._handle), ctypes.byref(counters), counters.cb):
        return counters.PeakWorkingSetSize
    return None


def execute(directory, c, name, command):
    directory = local(directory)
    target = child(directory / "stages", name + ".json")
    require(not target.exists(), "Stage receipt exists; no uncertain rerun")
    config(directory)
    logpath = child(directory / "stages", name + ".log")
    receipt = {"status": "running", "name": name, "command_argv": command, "started_utc": utc(),
               "supervisor_pid": os.getpid(), "source_sha256": c["source_sha256"], "log": ref(logpath),
               "rss_scope": "Windows direct child high-water mark; WSL launcher excludes Linux descendants"}
    start = time.perf_counter(); peak = None; process = None
    environment = os.environ.copy()
    environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        with logpath.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=ROOT, env=environment, stdin=subprocess.DEVNULL,
                                       stdout=log, stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            receipt["child_pid"] = process.pid
            atomic(target, receipt, fresh=True)
            last = 0.0
            while process.poll() is None:
                rss = observed_rss(process)
                if rss is not None:
                    peak = max(peak or 0, rss)
                elapsed = time.perf_counter() - start
                if elapsed - last >= 15:
                    atomic(directory / "progress.json", {"status": "running", "current_stage": name,
                           "supervisor_pid": os.getpid(), "child_pid": process.pid, "heartbeat_utc": utc(),
                           "stage_elapsed_seconds": elapsed, "observed_child_peak_rss_bytes": peak})
                    last = elapsed
                time.sleep(1)
            receipt["exit_code"] = process.returncode
            require(process.returncode == 0, "Stage failed; preserve " + ref(logpath))
        config(directory)
        receipt["status"] = "complete"
    except BaseException as error:
        receipt["status"] = "failed"; receipt["error"] = str(error)
        receipt["child_may_be_running"] = process is not None and process.poll() is None
        raise
    finally:
        receipt.update(finished_utc=utc(), elapsed_seconds=time.perf_counter() - start,
                       observed_child_peak_rss_bytes=peak)
        atomic(target, receipt)
    return receipt


def verify_map(base, mapping, expected=None):
    require(type(mapping) is dict and (expected is None or set(mapping) == set(expected)), "Hash inventory mismatch")
    for name, digest in mapping.items():
        path = child(base, name) if Path(base).is_relative_to(ROOT / ".local") else unlinked(Path(base) / name)
        require(ref(path) and len(digest) == 64 and sha(path) == digest, "Changed artifact/dependency: " + name)


def verify_model(c):
    model = c["model_id"]
    require(model in MODELS and c["kind"] == "ring_effective_model_v1", "Wrong effective-model identity")
    source = unlinked(ROOT / ("models/" + model + ".yaml"))
    require(c["source_model_ref"] == ref(source) and sha(source) == c["source_model_sha256"], "Wrong source model")
    body = source.read_bytes()
    if model == "GeRC02":
        require(body.count(b"lithium_annealing_time: 30minute") == 1, "Wrong frozen Li input")
        body = body.replace(b"lithium_annealing_time: 30minute", b"lithium_annealing_time: 50minute", 1)
        effective = child(ROOT / ".local", c["effective_model_ref"].removeprefix(".local/"))
        require(c["effective_model_ref"].startswith(".local/") and c["variant_id"] == "GeRC02_Li50min"
                and c["annealing_time_minutes"] == 50 and c["annealing_temperature_K"] == 553.15, "Wrong Li variant")
    else:
        effective = source
        require(c["effective_model_ref"] == ref(source) and c["variant_id"] == model and c["model_delta"] is None
                and c["annealing_time_minutes"] is None and c["annealing_temperature_K"] is None, "KM variant changed")
    require(effective.read_bytes() == body and sha(effective) == c["effective_model_sha256"], "Effective-model bytes changed")
    require(c["contact_potentials_V"] == {"1": 0, "2": 240 if model == "GeRC02" else -370}
            and c["stored_temperature_K"] == 78 and c["runtime_temperature_K"] == 77
            and c["readout_contact_id"] == 1 and c["geometry_unchanged"] is True, "Model convention/bias changed")
    verify_map(ROOT, c["dependencies_sha256"])


def stream_events(directory, manifest):
    expected = 0
    for chunk in manifest["chunks"]:
        require(Path(chunk["file"]).name == chunk["file"] and 1 <= chunk["count"] <= 100
                and chunk["first_global_decay_id"] == expected, "Invalid stream chunk")
        path = child(directory, chunk["file"])
        require(sha(path) == chunk["sha256"], "Changed stream chunk")
        count = 0
        with path.open(encoding="utf-8") as stream:
            for line in stream:
                event = json.loads(line)
                require(event["event_id"] == event["global_decay_id"] == expected, "Missing/duplicate primary")
                count += 1; expected += 1
                require(count <= chunk["count"], "Extra stream row")
                yield event
        require(count == chunk["count"], "Truncated stream")
    require(expected == manifest["primary_count"] and manifest["global_decay_id_range"] == [0, expected - 1], "Incomplete stream census")


def verify_transport(directory, model, count, seed):
    directory = local(directory)
    prepared = read(directory / "prepared.json"); run = read(directory / "run.json")
    manifest = read(directory / "stream/manifest.json")
    require(prepared["kind"] == "ring_cs137_prepared_v1" and prepared["producer_adapter"] == "ring_cs137_v1"
            and prepared["model_id"] == model and prepared["primary_count"] == count and prepared["seed"] == seed,
            "Transport intent mismatch")
    require(read(directory / "prepare-receipt.json")["status"] == "complete" and run["status"] == "complete"
            and run["returncode"] == 0 and run["versions"]["remage"] == "1.1.0" and run["versions"]["geant4"] == "11.3.2", "Nonterminal/unpinned transport")
    verify_model(prepared["model_contract"])
    verify_map(directory, prepared["files_sha256"])
    verify_map(ROOT / "transport", prepared["source_sha256"], BASE_PRODUCER)
    verify_map(ROOT, prepared["ring_source_sha256"], RING_PRODUCER)
    require(run["prepared_sha256"] == sha(directory / "prepared.json") and run["source_lh5_sha256"] == sha(directory / "truth.lh5"), "Transport output binding mismatch")
    require(manifest["kind"] == "cs137_decay_stream_v1" and manifest["producer_adapter"] == "ring_cs137_v1"
            and manifest["status"] == "complete", "Nonterminal ring stream")
    for key in ("model_id", "model_sha256", "model_contract", "primary_count", "coordinate_transform", "grouping_policy",
                "clock_policy", "source_sha256", "ring_source_sha256", "mounting_contract"):
        require(equal(manifest[key], prepared[key]), "Stream/prepared mismatch: " + key)
    for filename, key in (("prepared.json", "prepared_sha256"), ("run.json", "run_sha256"), ("truth.lh5", "source_lh5_sha256"),
                          ("scenario.json", "config_sha256"), ("geometry.gdml", "geometry_sha256"), ("run.mac", "macro_sha256")):
        require(sha(directory / filename) == manifest[key], "Stream binding mismatch: " + key)
    geometry = read(directory / "geometry-report.json")
    require(geometry["overlaps_passed"] is True and geometry["source_inside_fill"] is True, "Geometry acceptance failed")
    require(manifest["units"] == {"energy": "keV", "length": "mm", "time": "ns"}
            and manifest["clock_policy"] == "remage_initial_decay_secondaries_zero", "Units/clock changed")
    return prepared, run, manifest


def expected_readout(count):
    c = read(ROOT / "simulation/readout_demo.json")
    c["schema_version"] = 2; c["expected_primary_count"] = count; c.pop("max_total_samples")
    c.update(read(ROOT / PROFILE)["settings"])
    return c


def check_calibration(cal, c, eion):
    require(cal["method"] == "single delta-charge injection at t=0; sampled analog peak; fixed across events"
            and cal["energy_keV"] == c["calibration_energy_keV"] == 500 and cal["time_step_ns"] == 2,
            "Separate fixed injection calibration missing")
    require(all(type(cal[k]) in (int, float) and math.isfinite(cal[k]) and cal[k] > 0
                for k in ("charge_C", "peak_V", "volts_per_keV", "adc_lsb_V", "peak_time_ns")), "Invalid calibration")
    require(cal["ionisation_energy_eV"] == eion and math.isclose(cal["charge_C"], 500000 / eion * 1.602176634e-19, rel_tol=1e-12)
            and math.isclose(cal["volts_per_keV"], cal["peak_V"] / 500, rel_tol=1e-12)
            and cal["adc_lsb_V"] == c["adc_full_scale_V"] / 2 ** c["adc_bits"], "Calibration/config mismatch")


def verify_response(modeldir, model, count, policy):
    modeldir = local(modeldir)
    prepared, transport, manifest = verify_transport(modeldir / "transport", model, count, SEEDS[model])
    out = modeldir / "response"; report = read(out / "run.json"); envelope = read(out / "ring-response.json")
    require(report["kind"] == "native_response_v1" and report["status"] in KINDS and envelope["kind"] == "ring_native_response_v1"
            and envelope["status"] == report["status"] and envelope["native_report_sha256"] == sha(out / "run.json"), "Nonterminal/unbound ring response")
    require(envelope["model_contract"] == prepared["model_contract"] and envelope["new_field_solution"] is True
            and envelope["failure_policy"] == policy and envelope["effective_model_sha256"] == prepared["model_contract"]["effective_model_sha256"], "Response variant/cache/policy mismatch")
    verify_map(ROOT / "simulation", report["source_sha256"], NATIVE)
    verify_map(ROOT / "simulation", envelope["source_sha256"], (*NATIVE, "ring_stream.jl", "ring_response.jl"))
    artifacts = {"endpoints.csv", "endpoints.jsonl", "histograms.csv", "histograms.json", "input-contract.json", "input-prepared.json",
                 "profile-input.json", "profile.json", "readout-config.json", "scalars.csv", "scalars.jsonl", "signals.csv", "summary.html", "traces.jsonl", "truth.csv", "truth.jsonl"}
    if report["counts"]["native_failed_groups"]:
        artifacts.add("native-failures.jsonl")
    verify_map(out, report["artifacts"], artifacts)
    require(set(report["artifact_bytes"]) == artifacts and all(child(out, k).stat().st_size == v for k, v in report["artifact_bytes"].items()), "Artifact size mismatch")
    require(report["input_sha256"] == envelope["input_sha256"] == sha(modeldir / "transport/stream/manifest.json")
            and report["source_lh5_sha256"] == transport["source_lh5_sha256"]
            and report["model_sha256"] == envelope["source_model_sha256"] == prepared["model_sha256"], "Response source/input mismatch")
    require(equal(read(out / "input-contract.json"), manifest) and equal(read(out / "input-prepared.json"), prepared), "Copied source contract changed")
    expected = {"parcels": 16, "seed_family": 2609261, "diffusion": True, "end_drift_when_no_field": False,
                "self_repulsion": False, "drift_dt_ns": 2, "nominal_drift_cap_ns": 10000, "readout_contact_id": 1,
                "temperature_K": 77, "stored_temperature_K": 78, "native_failure_policy": policy,
                "charge_csv_policy": "examples", "bias_V": 240 if model == "GeRC02" else 370,
                "field_settings": {"precision_bits": 64, "min_spacing_mm": 0.05, "max_spacing_mm": 2, "sor": 1, "potential_rechecks": 4},
                "units": {"charge": "fC", "current": "nA", "voltage": "V", "energy": "keV", "time": "ns"},
                "native_failure_allowlist": ["Noncontact endpoint outside crystal", "Invalid waveform support"]}
    require(all(report.get(k) == v for k, v in expected.items()), "Native settings changed")
    require(report["environment"] == {"environment_manifest_sha256": sha(ROOT / "simulation/Manifest.toml"),
            "julia_version": "1.13.0", "ssd_version": "0.11.8", "project": "simulation/Project.toml", "manifest": "simulation/Manifest.toml"}, "Pinned SSD environment mismatch")
    require(report["readout_environment"]["julia_version"] == report["readout_environment"]["pinned_julia_version"] == "1.13.0"
            and report["readout_environment"]["json_version"] == "1.9.0"
            and report["readout_environment"]["manifest_sha256"] == sha(ROOT / "simulation/Manifest.toml")
            and report["readout_environment"]["project_sha256"] == sha(ROOT / "simulation/Project.toml"), "Readout environment mismatch")
    profile = read(ROOT / PROFILE); resolved = expected_readout(count)
    require(report["profile"] == read(out / "profile.json") == profile and report["profile_sha256"] == envelope["profile_sha256"]
            == sha(ROOT / PROFILE) == sha(out / "profile-input.json"), "Shared profile changed")
    require(read(out / "readout-config.json") == resolved and report["config_sha256"] == sha(out / "readout-config.json"), "Readout config differs beyond census")
    check_calibration(report["calibration"], resolved, report["ionisation_energy_eV"])
    require(envelope["calibration"] == report["calibration"] and envelope["counts"] == report["counts"], "Envelope summary changed")
    counts = {"initial_primaries": 0, "initial_decays": 0, "zero_deposit_primaries": 0, "groups": 0,
              "accepted": 0, "rejected": 0, "readout_rejected": 0, "native_failed_groups": 0,
              "saturated": 0, "line_photons": 0, "decay_photons": 0}
    positive = 0
    with (out / "truth.jsonl").open(encoding="utf-8") as truth, (out / "scalars.jsonl").open(encoding="utf-8") as scalars:
        for event in stream_events(modeldir / "transport/stream", manifest):
            require(equal(json.loads(next(truth)), event), "Truth identity/raw rows changed")
            scalar = json.loads(next(scalars)); energy = sum(x["energy_keV"] for x in event["steps"])
            require(scalar["record_kind"] == "decay" and scalar["event_id"] == scalar["global_decay_id"] == event["event_id"]
                    and scalar["raw_row_indices"] == [x["raw_row_index"] for x in event["steps"]]
                    and scalar["pulse_count"] == len(event["pulse_groups"]) and scalar["zero_deposit"] == (energy == 0)
                    and math.isclose(scalar["deposited_energy_keV"], energy, rel_tol=1e-12, abs_tol=1e-12), "Primary scalar census changed")
            counts["initial_primaries"] += 1; counts["initial_decays"] += 1; counts["zero_deposit_primaries"] += energy == 0
            counts["line_photons"] += event["line_photon_count"]; counts["decay_photons"] += event["decay_photon_count"]
            for group in event["pulse_groups"]:
                pulse = json.loads(next(scalars))
                require(pulse["record_kind"] == "pulse" and pulse["event_id"] == pulse["global_decay_id"] == event["event_id"]
                        and pulse["group_id"] == group["group_id"] and pulse["raw_row_indices"] == group["row_indices"], "Pulse identity changed")
                counts["groups"] += 1
                if pulse.get("status") == "native_transport_failed":
                    require(policy == "record" and pulse["native_error"]["message"] in report["native_failure_allowlist"], "Unexpected recorded failure")
                    require(pulse["readout"] is None and pulse["final_induced_keV"] is None and pulse["transport_flags"] is None, "Unknown response fabricated")
                    counts["native_failed_groups"] += 1; counts["rejected"] += 1
                else:
                    readout = pulse["readout"]
                    require(readout["current_balance"]["passed"] is True and math.isfinite(pulse["final_induced_keV"]), "Signed charge/current check failed")
                    require(pulse["accepted"] == readout["accepted"], "Readout selection mismatch")
                    counts["accepted"] += bool(pulse["accepted"]); counts["rejected"] += not pulse["accepted"]
                    counts["readout_rejected"] += not pulse["accepted"]; counts["saturated"] += bool(readout["saturated"])
                    positive += pulse["deposited_energy_keV"] > 0 and pulse["final_induced_keV"] != 0 and pulse["native_max_charge_keV"] > 0
        require(not truth.readline() and not scalars.readline(), "Extra response primary/group")
    require(all(report["counts"][k] == v for k, v in counts.items()) and counts["initial_primaries"] == count, "Independent response counts mismatch")
    require((report["status"] == "completed_with_native_failures") == (counts["native_failed_groups"] > 0), "Native status/count mismatch")
    require(read(out / "histograms.json")["normalization_denominators"] == report["counts"], "Histogram denominator changed")
    return {"status": report["status"], "counts": counts, "positive_native_groups": positive,
            "transport_seconds": transport["remage_wall_s"], "field_timings": report["field_timings"],
            "native_seconds": report["native_drift_and_charge_seconds"], "electronics_seconds": report["electronics_seconds"],
            "response_process_peak_rss_bytes": report["process_peak_rss_bytes"],
            "native_report_sha256": sha(out / "run.json"), "ring_response_sha256": sha(out / "ring-response.json")}


def pilot_gate(modeldir, model):
    result = verify_response(modeldir, model, 500, "abort")
    require(result["status"] == "completed_provisional_native_response" and result["counts"]["native_failed_groups"] == 0
            and result["counts"]["groups"] > 0 and result["positive_native_groups"] > 0 and result["counts"]["accepted"] > 0,
            "Pilot cannot promote: clean positive native integration and an accepted readout are required")
    return result


def matching(pilotdir, productiondir):
    p = read(pilotdir / "transport/prepared.json"); r = read(productiondir / "transport/prepared.json")
    for key in ("model_id", "model_sha256", "seed", "source_position_global_mm", "coordinate_transform", "contour_rz_mm",
                "grouping_policy", "clock_policy", "source_sha256", "ring_source_sha256", "exporter_sha256", "mounting_contract"):
        require(equal(p[key], r[key]), "Production differs from accepted pilot: " + key)
    pc, rc = p["model_contract"].copy(), r["model_contract"].copy()
    pc.pop("effective_model_ref"); rc.pop("effective_model_ref")
    require(pc == rc and sha(pilotdir / "transport/scenario.json") == sha(productiondir / "transport/scenario.json")
            and sha(pilotdir / "transport/geometry.gdml") == sha(productiondir / "transport/geometry.gdml"), "Production effective model/geometry changed")


def model_pipeline(directory, c, phase, model):
    count = c["pilot_count"] if phase == "pilot500" else c["production_count"]
    policy = "abort" if phase == "pilot500" else c["production_native_failure_policy"]
    modeldir = child(directory, phase + "/" + model)
    require(not modeldir.exists(), "Model stage exists; failed/incomplete science must not repeat")
    modeldir.mkdir(parents=True)
    prefix = phase + "-" + model + "-"
    execute(directory, c, prefix + "prepare", transport_command("prepare", "--model", model, "--output", ref(modeldir / "transport"),
            "--exporter", EXPORTER, "--events", str(count), "--seed", str(SEEDS[model])))
    if phase == "production10000":
        pilot_gate(directory / "pilot500" / model, model)
        matching(directory / "pilot500" / model, modeldir)
    execute(directory, c, prefix + "transport", transport_command("run", "--directory", ref(modeldir / "transport")))
    execute(directory, c, prefix + "extract", transport_command("extract", "--directory", ref(modeldir / "transport"), "--chunk-size", "100"))
    verify_transport(modeldir / "transport", model, count, SEEDS[model])
    execute(directory, c, prefix + "response", response_command(c, modeldir, policy))
    result = pilot_gate(modeldir, model) if phase == "pilot500" else verify_response(modeldir, model, count, policy)
    atomic(modeldir / "VERIFIED.json", result, fresh=True)
    return result


def selected(model):
    require(model == "both" or model in MODELS, "Unsupported model selection")
    return MODELS if model == "both" else (model,)


def phase_name(phase):
    require(phase in ("pilot", "production"), "Invalid campaign phase")
    return "pilot500" if phase == "pilot" else "production10000"


def verify(directory, phase="pilot", model="both"):
    directory = local(directory); c = config(directory)
    leaf = phase_name(phase); results = {}
    for item in selected(model):
        result = pilot_gate(directory / leaf / item, item) if phase == "pilot" else verify_response(directory / leaf / item, item, 10000, c["production_native_failure_policy"])
        require(equal(result, read(directory / leaf / item / "VERIFIED.json")), "Saved verification changed")
        verified = read(directory / leaf / item / "VERIFIED.json")
        require(verified == result, "Terminal verification changed")
        for stage in ("prepare", "transport", "extract", "response"):
            receipt = read(directory / "stages" / (leaf + "-" + item + "-" + stage + ".json"))
            require(receipt["status"] == "complete" and receipt["exit_code"] == 0
                    and receipt["source_sha256"] == c["source_sha256"], "Stage receipt incomplete/changed")
        results[leaf + "/" + item] = result
    status = "completed_with_native_failures" if any(x["counts"]["native_failed_groups"] for x in results.values()) else "completed"
    complete_path = directory / (phase + "-" + model + "-COMPLETE.json")
    if complete_path.exists():
        complete = read(complete_path)
        require(complete["status"] == status and complete["config_sha256"] == sha(directory / "config.json")
                and equal(complete["results"], results), "Campaign terminal receipt changed")
        verify_map(directory, complete["stage_receipt_sha256"])
    return {"status": status, "results": results, "new_science_stages": 0}


def run(directory, phase="pilot", model="both"):
    directory = local(directory); c = config(directory)
    leaf = phase_name(phase); models = selected(model); name = phase + "-" + model
    complete_path = directory / (name + "-COMPLETE.json")
    if complete_path.exists():
        return verify(directory, phase, model)
    for item in models:
        require(not (directory / leaf / item).exists(), "Existing selected model stage requires inspection; no science rerun")
        if phase == "production":
            pilot_gate(directory / "pilot500" / item, item)
    lock = directory / ".supervisor.lock"
    lock.mkdir()  # Atomic exclusive ownership. Never delete a prior lock.
    atomic(lock / "owner.json", {"pid": os.getpid(), "created_utc": utc()}, fresh=True)
    start = time.perf_counter(); results = {}
    atomic(directory / "progress.json", {"status": "running", "phase": phase, "model_selection": model,
           "supervisor_pid": os.getpid(), "started_utc": utc()})
    try:
        for item in models:
            results[leaf + "/" + item] = model_pipeline(directory, c, leaf, item)
        config(directory)
        status = "completed_with_native_failures" if any(x["counts"]["native_failed_groups"] for x in results.values()) else "completed"
        complete = {"kind": c["kind"], "status": status, "finished_utc": utc(), "supervisor_pid": os.getpid(),
                    "config_sha256": sha(directory / "config.json"), "results": results,
                    "orchestration_elapsed_seconds": time.perf_counter() - start,
                    "timing_scope": "Supervisor wall time including startup, checks, exports; measured stage compute is separate",
                    "stage_receipt_sha256": {ref(p).removeprefix(ref(directory) + "/"): sha(p) for p in (directory / "stages").glob("*.json")},
                    "runtime": {"supervisor_python": sys.version, "platform": platform.platform()},
                    "new_field_cache_reuse_count": 0, "processing_completion_is_not_validation": True}
        atomic(complete_path, complete, fresh=True)
        atomic(directory / "progress.json", {"status": status, "finished_utc": utc(), "results": results,
               "supervisor_pid": os.getpid(), "orchestration_elapsed_seconds": time.perf_counter() - start})
        return complete
    except BaseException as error:
        atomic(directory / "progress.json", {"status": "failed", "error": str(error), "finished_utc": utc(), "results": results,
               "supervisor_pid": os.getpid(), "orchestration_elapsed_seconds": time.perf_counter() - start,
               "next_step": "Inspect receipts, exact error and actual process identities; preserve failed/incomplete data. No automatic rerun."})
        raise
    finally:
        unresolved = any(read(p).get("child_may_be_running", False) for p in (directory / "stages").glob("*.json"))
        atomic(directory / (name + "-supervisor-exit.json"), {"pid": os.getpid(), "finished_utc": utc(),
               "elapsed_seconds": time.perf_counter() - start, "unresolved_child_intent": unresolved}, fresh=True)
        if not unresolved:
            (lock / "owner.json").unlink(); lock.rmdir()


def start(directory, phase="pilot", model="both"):
    directory = local(directory); config(directory)
    require(os.name == "nt", "Detached launch uses the existing Windows host")
    leaf = phase_name(phase); models = selected(model); name = phase + "-" + model
    require(not (directory / ".supervisor.lock").exists(), "Prior worker lock requires inspection")
    # Any prior detached worker must have a matching exit record before another launch.
    for launcher in directory.glob("*-launcher.json"):
        require(launcher.with_name(launcher.name.replace("-launcher.json", "-supervisor-exit.json")).is_file(),
                "Prior detached worker has not recorded exit; inspect actual processes")
    for item in models:
        require(not (directory / leaf / item).exists(), "Existing selected model stage cannot rerun")
        if phase == "production":
            pilot_gate(directory / "pilot500" / item, item)
    ticket = directory / (name + "-launch-ticket.json")
    with ticket.open("x", encoding="utf-8") as stream:
        json.dump({"created_utc": utc(), "intent": "one serial campaign; duplicate launch refused"}, stream)
    command = [sys.executable, "-u", "-B", str(ROOT / "tools/ring_run.py"), "run", "--directory", str(directory),
               "--phase", phase, "--model", model]
    logpath = directory / (name + "-supervisor.log")
    with logpath.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
                                   creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
                                   close_fds=True)
    record = {"pid": process.pid, "started_utc": utc(), "command_argv": command, "output_root": ref(directory),
              "log": ref(logpath), "source_sha256": config(directory)["source_sha256"]}
    atomic(directory / (name + "-launcher.json"), record, fresh=True)
    return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare"); p.add_argument("--output", required=True); p.add_argument("--threads", type=int, choices=(1, 2), default=2)
    p.add_argument("--production-native-failure-policy", choices=("abort", "record"), default="record")
    for command in ("start", "run", "verify"):
        p = sub.add_parser(command); p.add_argument("--directory", required=True)
        p.add_argument("--phase", choices=("pilot", "production"), default="pilot")
        p.add_argument("--model", choices=("both", *MODELS), default="both")
    args = parser.parse_args()
    value = prepare(args.output, args.threads, args.production_native_failure_policy) if args.command == "prepare" else globals()[args.command](args.directory, args.phase, args.model)
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
