"""Additive KM lifecycle: saved 500-pilot readout, then serial 10K production.

The original negative native signals and rejected readout remain immutable.
Only the approved fixed -1 electronics wiring and an independent negative
500-keV injection are added. Existing/uncertain outputs never trigger reruns.
"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

import ring_run as r
import ring_production as provenance

MODEL = "KMRC01_candidate"
CAMPAIGN = r.ROOT / ".local/ring-cs137-v1"
DERIVATIVE = "readout-inverted-v1"
WRITER = ".local/ring-cs137-v1/KM-POLARITY-WRITER-v1.json"
PILOT_RUN_SHA = "6b9592faab09f09e2c7f81c4054748793e19032856e82eb1d893d1a29b64349b"
PILOT_ENVELOPE_SHA = "f5f71daad48f32164f7f1d1c0461bbfb7c2e0ac7f4daa614c4c80c39fa5c3530"
EXTRA_SOURCES = ("tools/km_ring_run.py", "tools/test_km_ring_run.py",
                 "tools/ring_production.py", "tools/test_ring_production.py",
                 "simulation/ring_polarity.jl", "simulation/test_ring_polarity.jl", WRITER)
ARTIFACTS = {"endpoints.csv", "endpoints.jsonl", "histograms.csv", "histograms.json",
             "input-contract.json", "input-prepared.json", "profile-input.json", "profile.json",
             "readout-config.json", "scalars.csv", "scalars.jsonl", "signals.csv", "summary.html",
             "traces.jsonl", "truth.csv", "truth.jsonl"}
DERIVATIVE_ARTIFACTS = {"negative-injection.json", "scalars.jsonl", "traces.jsonl", "readout-input.csv"}
SIGNAL_HEADER = ["event_id", "global_decay_id", "group_id", "time_since_origin_ns", "induced_equivalent_energy_keV"]
INPUT_HEADER = ["event_id", "global_decay_id", "group_id", "time_since_origin_ns", "raw_native_charge_keV",
                "electronics_input_charge_keV", "raw_native_charge_fC", "electronics_input_charge_fC",
                "raw_native_current_nA", "electronics_input_current_nA"]
NEGATIVE_METHOD = ("independent negative delta-charge at t=0 through fixed -1 KM wiring; unchanged sampled "
                   "analog transfer; one slope across all events")


def census_id(value):
    r.require(type(value) is int and value >= 0, "Invalid discrete identity")
    return value


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def key(record):
    return tuple(census_id(record[x]) for x in ("event_id", "global_decay_id", "group_id"))


def wiring(value):
    expected = {"kind": "fixed_km_readout_wiring_v1", "model_id": MODEL, "factor": -1.0,
                "stage": "native signed induced charge -> electronics input",
                "input_unit": "signed induced-equivalent keV", "output_unit": "electronics-input equivalent keV",
                "raw_signal_policy": "Original signed native charge/current, endpoints and truth are unchanged; no abs or event-dependent sign/gain"}
    r.require(r.equal(value, expected), "Fixed KM electronics wiring changed")


def dependencies():
    sources = r.dependencies()
    sources.update({name: r.sha(r.unlinked(r.ROOT / name)) for name in EXTRA_SOURCES})
    writer = r.read(r.ROOT / WRITER)
    r.require(writer["kind"] == "km_fixed_polarity_writer_v1" and writer["writer_stopped"] is True
              and writer["no_more_source_writes"] is True, "Polarity writer has not frozen its source")
    for name, record in writer["source_records"].items():
        r.require(name in sources and sources[name] == record["sha256"]
                  and (r.ROOT / name).stat().st_size == record["bytes"], "Polarity writer freeze changed")
    return dict(sorted(sources.items()))


def directory_path(directory):
    directory = r.local(directory)
    r.require(directory == r.unlinked(CAMPAIGN), "Use the existing ring campaign root")
    return directory


def original(directory):
    c = r.config(directory)
    r.require(c["julia_threads"] == 2 and c["production_native_failure_policy"] == "record",
              "KM must retain the accepted two-thread/record production configuration")
    return c


def configuration(directory):
    directory = directory_path(directory); base = original(directory)
    c = r.read(directory / "km-config.json")
    r.require(r.sha(directory / "km-config.json") == (directory / "km-config.sha256").read_text().strip(),
              "KM configuration bytes changed")
    expected = {"kind": "km_fixed_polarity_campaign_v1", "model": MODEL, "factor": -1,
                "pilot_count": 500, "production_count": 10000, "julia_threads": 2,
                "production_native_failure_policy": "record", "production_charge_csv_policy": "all",
                "original_config_sha256": r.sha(directory / "config.json"),
                "pilot_native_report_sha256": PILOT_RUN_SHA, "pilot_ring_envelope_sha256": PILOT_ENVELOPE_SHA,
                "derivative_leaf": DERIVATIVE, "profile_ref": r.PROFILE,
                "resource_bounds": base["resource_bounds"], "julia_executable_sha256": base["julia_executable_sha256"]}
    r.require(all(r.equal(c.get(k), v) for k, v in expected.items()), "KM settings changed")
    r.require(c["source_sha256"] == dependencies(), "Source changed after KM freeze; preserve science and inspect")
    return c


def idle(directory, own_name=None):
    r.require(not (directory / ".supervisor.lock").exists(), "Existing supervisor lock requires owned inspection")
    for launcher in directory.glob("*-launcher.json"):
        if own_name is not None and launcher.name == own_name + "-launcher.json":
            continue
        exit_path = launcher.with_name(launcher.name.replace("-launcher.json", "-supervisor-exit.json"))
        r.require(exit_path.is_file() and r.read(exit_path).get("unresolved_child_intent") is False,
                  "Prior supervisor has no clean exit; inspect actual workers")


def check_readout_config(out, report, count):
    resolved = r.expected_readout(count)
    r.require(r.equal(r.read(out / "readout-config.json"), resolved)
              and report["config_sha256"] == r.sha(out / "readout-config.json"),
              "Readout config differs beyond census, even if rehashed")
    return resolved


def native_settings(report, policy, charge_policy):
    expected = {"model_id": MODEL, "parcels": 16, "seed_family": 2609261, "diffusion": True,
                "end_drift_when_no_field": False, "self_repulsion": False, "drift_dt_ns": 2,
                "nominal_drift_cap_ns": 10000, "readout_contact_id": 1, "temperature_K": 77,
                "stored_temperature_K": 78, "native_failure_policy": policy, "charge_csv_policy": charge_policy,
                "bias_V": 370, "field_settings": {"precision_bits": 64, "min_spacing_mm": 0.05,
                    "max_spacing_mm": 2, "sor": 1, "potential_rechecks": 4},
                "units": {"charge": "fC", "current": "nA", "voltage": "V", "energy": "keV", "time": "ns"},
                "native_failure_allowlist": ["Noncontact endpoint outside crystal", "Invalid waveform support"]}
    r.require(all(report.get(k) == v for k, v in expected.items()), "Native settings changed")
    geometry = report["geometry_checks"]
    r.require(geometry["field_cache_used"] is False and geometry["proper_coordinate_transform"] is True
              and geometry["ssd_contour_matches"] is True, "Native geometry checks failed")


def records(path):
    with path.open(encoding="utf-8") as stream:
        for line in stream:
            r.require(bool(line.strip()), "Empty ledger row")
            yield json.loads(line, parse_constant=lambda value: r.require(False, "Nonfinite ledger JSON: " + value))


def native_ledger(modeldir, manifest, report, policy):
    out = modeldir / "response"; truth = iter(records(out / "truth.jsonl")); scalars = iter(records(out / "scalars.jsonl"))
    counts = dict.fromkeys(("initial_primaries", "initial_decays", "zero_deposit_primaries", "groups", "accepted",
                           "rejected", "readout_rejected", "native_failed_groups", "saturated", "line_photons", "decay_photons"), 0)
    r.require(all(type(value) is int and value >= 0 for value in report["counts"].values()), "Invalid native integer counts")
    successful = {}; negative = 0
    for event in r.stream_events(modeldir / "transport/stream", manifest):
        census_id(event["event_id"]); census_id(event["global_decay_id"])
        r.require(r.equal(next(truth, None), event), "Truth identity/raw rows changed")
        scalar = next(scalars, None); energy = sum(x["energy_keV"] for x in event["steps"])
        r.require(scalar is not None and scalar["record_kind"] == "decay"
                  and census_id(scalar["event_id"]) == census_id(scalar["global_decay_id"]) == event["event_id"]
                  and scalar["group_id"] is None and scalar["raw_row_indices"] == [x["raw_row_index"] for x in event["steps"]]
                  and scalar["pulse_count"] == len(event["pulse_groups"]) and scalar["zero_deposit"] is (energy == 0)
                  and math.isclose(scalar["deposited_energy_keV"], energy, rel_tol=1e-12, abs_tol=1e-12)
                  and r.equal(scalar["material_energy_keV"], event["material_energy_keV"])
                  and scalar["full_energy_closure"] is None, "Primary census/material ledger changed")
        counts["initial_primaries"] += 1; counts["initial_decays"] += 1; counts["zero_deposit_primaries"] += energy == 0
        counts["line_photons"] += event["line_photon_count"]; counts["decay_photons"] += event["decay_photon_count"]
        byrow = {x["raw_row_index"]: x for x in event["steps"]}
        for group in event["pulse_groups"]:
            pulse = next(scalars, None)
            r.require(pulse is not None and pulse["record_kind"] == "pulse"
                      and key(pulse) == (event["event_id"], event["global_decay_id"], census_id(group["group_id"]))
                      and pulse["raw_row_indices"] == group["row_indices"] and r.equal(pulse["group"], group)
                      and pulse["origin_time_ns"] == group["origin_time_ns"]
                      and math.isclose(pulse["deposited_energy_keV"], sum(byrow[x]["energy_keV"] for x in group["row_indices"]),
                                       rel_tol=1e-12, abs_tol=1e-12), "Pulse identity/delay/raw-row ledger changed")
            counts["groups"] += 1
            if pulse.get("status") == "native_transport_failed":
                r.require(policy == "record" and pulse["native_error"]["message"] in report["native_failure_allowlist"]
                          and pulse["readout"] is None and pulse["final_induced_keV"] is None
                          and pulse["transport_flags"] is None and pulse["accepted"] is False,
                          "Native failure unknowns or exact error changed")
                counts["native_failed_groups"] += 1; counts["rejected"] += 1
            else:
                readout = pulse["readout"]
                r.require(readout["current_balance"]["passed"] is True and finite(pulse["final_induced_keV"])
                          and type(pulse["accepted"]) is bool and pulse["accepted"] == readout["accepted"],
                          "Native signed charge/current check failed")
                counts["accepted"] += pulse["accepted"]; counts["rejected"] += not pulse["accepted"]
                counts["readout_rejected"] += not pulse["accepted"]; counts["saturated"] += bool(readout["saturated"])
                negative += pulse["deposited_energy_keV"] > 0 and pulse["final_induced_keV"] < 0 and pulse["native_min_charge_keV"] < 0
                successful[key(pulse)] = pulse
    r.require(next(truth, None) is None and next(scalars, None) is None, "Extra primary/pulse ledger row")
    r.require(all(report["counts"][k] == v for k, v in counts.items()) and counts["initial_primaries"] == manifest["primary_count"],
              "Independent native census differs")
    return counts, successful, negative


def signal_rows(path):
    with path.open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream); r.require(next(reader, None) == SIGNAL_HEADER, "Unexpected saved signal schema")
        for row in reader:
            r.require(len(row) == 5 and all(x.isascii() and x.isdecimal() and str(int(x)) == x for x in row[:3]),
                      "Invalid saved signal identity")
            t, q = map(float, row[3:]); r.require(finite(t) and finite(q), "Nonfinite saved signal")
            yield tuple(map(int, row[:3])), t, q


def verify_signals(out, report, successful):
    current = None; seen = []; total = 0; samples = 0; previous_t = None; previous_q = None
    def finish():
        pulse = successful[current]
        r.require(samples == pulse["readout"]["input_sample_count"] and previous_t == pulse["charge_end_ns"]
                  and r.equal(previous_q, pulse["final_induced_keV"]), "Saved charge/scalar coverage differs")
    for identity, t, q in signal_rows(out / "signals.csv"):
        r.require(identity in successful, "Failed/unknown group has a saved signal")
        if current != identity:
            if current is not None:
                finish()
            r.require(identity not in seen and t == 0 and q == 0, "Noncontiguous/invalid saved signal start")
            seen.append(identity); current = identity; samples = 0; previous_t = None
        r.require(previous_t is None or t - previous_t == report["drift_dt_ns"], "Saved native time grid changed")
        previous_t, previous_q = t, q; samples += 1; total += 1
    if current is not None:
        finish()
    r.require(seen == list(successful) and total == report["counts"]["native_charge_samples"], "Incomplete/extra saved native signals")


def verify_native(modeldir, count, policy, charge_policy):
    modeldir = r.local(modeldir); prepared, transport, manifest = r.verify_transport(modeldir / "transport", MODEL, count, r.SEEDS[MODEL])
    provenance.science_artifacts(modeldir)
    out = modeldir / "response"; report = r.read(out / "run.json"); envelope = r.read(out / "ring-response.json")
    r.require(report["kind"] == "native_response_v1" and report["status"] in r.KINDS
              and envelope["kind"] == "ring_native_response_v1" and envelope["status"] == report["status"]
              and envelope["native_report_sha256"] == r.sha(out / "run.json"), "Nonterminal/unbound native response")
    r.require(envelope["model_contract"] == report["geometry_checks"]["model_contract"] == prepared["model_contract"]
              and envelope["new_field_solution"] is True and envelope["failure_policy"] == policy
              and envelope["effective_model_sha256"] == prepared["model_contract"]["effective_model_sha256"], "Native model/cache/policy differs")
    r.verify_map(r.ROOT / "simulation", report["source_sha256"], r.NATIVE)
    r.verify_map(r.ROOT / "simulation", envelope["source_sha256"], (*r.NATIVE, "ring_stream.jl", "ring_response.jl"))
    expected = ARTIFACTS | ({"native-failures.jsonl"} if report["counts"]["native_failed_groups"] else set())
    r.verify_map(out, report["artifacts"], expected)
    r.require(set(report["artifact_bytes"]) == expected and all(r.child(out, n).stat().st_size == b for n, b in report["artifact_bytes"].items()), "Native artifact bytes differ")
    r.require(report["input_sha256"] == envelope["input_sha256"] == r.sha(modeldir / "transport/stream/manifest.json")
              and report["source_lh5_sha256"] == transport["source_lh5_sha256"]
              and report["model_sha256"] == envelope["source_model_sha256"] == prepared["model_sha256"]
              and r.equal(r.read(out / "input-contract.json"), manifest) and r.equal(r.read(out / "input-prepared.json"), prepared),
              "Native source/input binding differs")
    native_settings(report, policy, charge_policy)
    r.require(report["environment"] == {"environment_manifest_sha256": r.sha(r.ROOT / "simulation/Manifest.toml"),
              "julia_version": "1.13.0", "ssd_version": "0.11.8", "project": "simulation/Project.toml", "manifest": "simulation/Manifest.toml"}, "Pinned SSD environment differs")
    env = report["readout_environment"]
    r.require(env["julia_version"] == env["pinned_julia_version"] == "1.13.0" and env["json_version"] == "1.9.0"
              and env["manifest_sha256"] == r.sha(r.ROOT / "simulation/Manifest.toml")
              and env["project_sha256"] == r.sha(r.ROOT / "simulation/Project.toml"), "Pinned readout environment differs")
    r.require(report["profile"] == r.read(out / "profile.json") == r.read(r.ROOT / r.PROFILE)
              and report["profile_sha256"] == envelope["profile_sha256"] == r.sha(r.ROOT / r.PROFILE)
              == r.sha(out / "profile-input.json"), "Native profile changed")
    resolved = check_readout_config(out, report, count)
    r.check_calibration(report["calibration"], resolved, report["ionisation_energy_eV"])
    r.require(envelope["counts"] == report["counts"] and envelope["calibration"] == report["calibration"]
              and envelope["field_fingerprint"] == report["field_fingerprint"], "Native envelope summary differs")
    counts, successful, negative = native_ledger(modeldir, manifest, report, policy)
    verify_signals(out, report, successful)
    r.require((report["status"] == "completed_with_native_failures") == (counts["native_failed_groups"] > 0)
              and r.read(out / "histograms.json")["normalization_denominators"] == report["counts"], "Native status/denominator differs")
    return {"status": report["status"], "counts": report["counts"], "negative_native_groups": negative,
            "native_report_sha256": r.sha(out / "run.json"), "ring_response_sha256": r.sha(out / "ring-response.json"),
            "transport_seconds": transport["remage_wall_s"], "field_timings": report["field_timings"],
            "native_seconds": report["native_drift_and_charge_seconds"], "original_electronics_seconds": report["electronics_seconds"],
            "native_process_peak_rss_bytes": report["process_peak_rss_bytes"]}


def pilot_source(directory):
    base = original(directory); modeldir = directory / "pilot500" / MODEL
    r.require(r.sha(modeldir / "response/run.json") == PILOT_RUN_SHA
              and r.sha(modeldir / "response/ring-response.json") == PILOT_ENVELOPE_SHA, "Original pilot authority changed")
    result = verify_native(modeldir, 500, "abort", "examples")
    r.require(result["status"] == "completed_provisional_native_response" and result["counts"]["native_failed_groups"] == 0
              and result["counts"]["groups"] > 0 and result["negative_native_groups"] == result["counts"]["groups"],
              "Pilot lacks clean correctly signed native response")
    paths = [directory / "stages" / ("pilot500-" + MODEL + "-" + s + ".json") for s in ("prepare", "transport", "extract", "response")]
    supervisor = provenance.stages(base, modeldir, [r.read(p) for p in paths])
    launchers = [p for p in directory.glob("pilot-*-launcher.json") if r.read(p)["pid"] == supervisor]
    r.require(len(launchers) == 1, "Actual pilot launcher missing/ambiguous")
    launcher = launchers[0]; launch = r.read(launcher)
    provenance.launcher_intent(base, directory, MODEL, launcher.name.removeprefix("pilot-").removesuffix("-launcher.json"), launch)
    exited = launcher.with_name(launcher.name.replace("-launcher.json", "-supervisor-exit.json")); terminal = r.read(exited)
    r.require(terminal["pid"] == supervisor and terminal["unresolved_child_intent"] is False, "Original pilot supervisor uncertain")
    paths.extend((launcher, exited, directory / "config.json"))
    return {"kind": "actual_signed_km_pilot_source_v1", "result": result,
            "execution_receipt_sha256": {r.ref(p): r.sha(p) for p in paths}, "original_positive_readout_gate_promoted": False}


def prepare(directory):
    directory = directory_path(directory); idle(directory)
    r.require(not (directory / "km-config.json").exists() and not (directory / "km-stages").exists(), "KM control exists; inspect and verify")
    base = original(directory); pilot = pilot_source(directory); sources = dependencies()
    c = {"kind": "km_fixed_polarity_campaign_v1", "created_utc": r.utc(), "model": MODEL, "factor": -1,
         "pilot_count": 500, "production_count": 10000, "julia_threads": 2, "production_native_failure_policy": "record",
         "production_charge_csv_policy": "all", "original_config_sha256": r.sha(directory / "config.json"),
         "pilot_native_report_sha256": PILOT_RUN_SHA, "pilot_ring_envelope_sha256": PILOT_ENVELOPE_SHA,
         "derivative_leaf": DERIVATIVE, "profile_ref": r.PROFILE, "resource_bounds": base["resource_bounds"],
         "julia_executable_sha256": base["julia_executable_sha256"], "source_sha256": sources, "pilot_source": pilot,
         "scope": "Fixed electronics wiring engineering example; no calibrated Li CCE, noise, physical resolution or experimental fit",
         "resume_policy": "Verify terminal receipts first. Preserve incomplete/failing outputs; no automatic rerun."}
    (directory / "km-stages").mkdir()
    r.atomic(directory / "km-config.json", c, fresh=True)
    (directory / "km-config.sha256").write_text(r.sha(directory / "km-config.json") + "\n", encoding="ascii")
    r.atomic(directory / "km-progress.json", {"status": "prepared", "new_radiation_stages": 0, "new_native_stages": 0}, fresh=True)
    return c


def model_directory(directory, phase):
    r.require(phase in ("pilot", "production"), "Unsupported KM phase")
    return directory / ("pilot500" if phase == "pilot" else "production10000") / MODEL


def response_command(c, modeldir):
    command = r.response_command(c, modeldir, "record")
    command[command.index("--charge-csv") + 1] = "all"
    return command


def derivative_command(c, modeldir):
    return [str(r.JULIA), "--startup-file=no", "--compiled-modules=existing", "--threads=" + str(c["julia_threads"]),
            "--project=simulation", "simulation/ring_polarity.jl", "--input", r.ref(modeldir / "response"),
            "--source-run-sha256", r.sha(modeldir / "response/run.json"), "--source-envelope-sha256",
            r.sha(modeldir / "response/ring-response.json"), "--output", r.ref(modeldir / DERIVATIVE)]


def negative_calibration(report, injection, native):
    cal = report["calibration"]; c = report["config"]; eion = native["ionisation_energy_eV"]
    expected_charge = 500000 / eion * 1.602176634e-19
    r.require(cal["method"] == NEGATIVE_METHOD and cal["energy_keV"] == c["calibration_energy_keV"] == 500
              and cal["wiring_factor"] == -1 and cal["time_step_ns"] == 2 and cal["ionisation_energy_eV"] == eion
              and finite(cal["raw_charge_C"]) and cal["raw_charge_C"] < 0
              and cal["electronics_input_charge_C"] == cal["charge_C"] == -cal["raw_charge_C"]
              and math.isclose(cal["charge_C"], expected_charge, rel_tol=1e-12), "Separate independent negative injection missing")
    r.require(all(finite(cal[k]) and cal[k] > 0 for k in ("peak_V", "volts_per_keV", "adc_lsb_V", "peak_time_ns"))
              and math.isclose(cal["volts_per_keV"], cal["peak_V"] / 500, rel_tol=1e-12)
              and cal["adc_lsb_V"] == c["adc_full_scale_V"] / 2 ** c["adc_bits"], "Negative injection gain/ADC differs")
    r.require(injection["kind"] == "independent_negative_charge_injection_v1" and injection["input_is_independent_of_event_truth"] is True
              and injection["energy_keV"] == 500 and r.equal(injection["calibration"], cal)
              and injection["raw_delta_charge_C"] == cal["raw_charge_C"]
              and injection["electronics_input_delta_charge_C"] == cal["charge_C"], "Negative injection record differs")
    wiring(injection["wiring"])
    t, pre, shaped = injection["time_ns"], injection["preamp_V"], injection["shaped_V"]
    r.require(len(t) == len(pre) == len(shaped) and 3 <= len(t) <= c["max_samples_per_event"]
              and all(finite(x) for values in (t, pre, shaped) for x in values)
              and t == [2 * i for i in range(len(t))] and t[-1] <= c["max_window_ns"]
              and max(shaped) == cal["peak_V"] and t[shaped.index(max(shaped))] == cal["peak_time_ns"]
              and min(pre) < 0, "Independent negative injection trace differs")


def derivative_ledger(modeldir, report, native):
    out = modeldir / DERIVATIVE; derived = iter(records(out / "scalars.jsonl")); traces = iter(records(out / "traces.jsonl"))
    counts = {"accepted": 0, "rejected": 0, "readout_rejected": 0, "saturated": 0, "analog_samples": 0}
    changed = {"readout", "accepted", "rejection_reason", "trace_saved"}
    added = {"original_readout", "original_accepted", "original_rejection_reason", "original_trace_saved",
             "electronics_input_final_charge_keV", "readout_wiring"}
    for raw in records(modeldir / "response/scalars.jsonl"):
        adapted = next(derived, None)
        r.require(adapted is not None, "Derivative lost a primary/group")
        if raw["record_kind"] == "decay" or raw.get("status") == "native_transport_failed":
            r.require(r.equal(raw, adapted), "Derivative altered zero/truth/native-failure records")
            if raw["record_kind"] == "pulse":
                counts["rejected"] += 1
            continue
        r.require(set(adapted) == set(raw) | added | {"trace_saved"}
                  and r.equal({k: v for k, v in adapted.items() if k not in changed | added},
                              {k: v for k, v in raw.items() if k not in changed}), "Derivative changed native truth/endpoints/flags/delays")
        r.require(r.equal(adapted["original_readout"], raw["readout"]) and adapted["original_accepted"] is raw["accepted"]
                  and adapted["original_rejection_reason"] == raw["rejection_reason"]
                  and adapted["original_trace_saved"] is raw.get("trace_saved", False) and adapted["trace_saved"] is True,
                  "Original readout rejection/diagnostics changed")
        wiring(adapted["readout_wiring"]); result = adapted["readout"]; wiring(result["wiring"])
        r.require(result["current_balance"]["passed"] is True
                  and result["raw_native_final_charge_keV"] == raw["final_induced_keV"]
                  and result["raw_native_min_charge_keV"] == raw["native_min_charge_keV"]
                  and result["raw_native_max_charge_keV"] == raw["native_max_charge_keV"]
                  and result["raw_native_any_negative_charge"] is raw["native_any_negative_charge"]
                  and adapted["electronics_input_final_charge_keV"] == -raw["final_induced_keV"]
                  and type(result["accepted"]) is bool and adapted["accepted"] is result["accepted"]
                  and adapted["rejection_reason"] == result["rejection_reason"], "Fixed wiring/native diagnostics differ")
        expected_energy = (result["adc_code"] + 0.5) * report["calibration"]["adc_lsb_V"] / report["calibration"]["volts_per_keV"]
        r.require(result["reconstructed_energy_keV"] == (expected_energy if result["accepted"] else None), "Reconstructed energy is not from the shared injection calibration")
        counts["accepted"] += result["accepted"]; counts["rejected"] += not result["accepted"]
        counts["readout_rejected"] += not result["accepted"]; counts["saturated"] += bool(result["saturated"])
        counts["analog_samples"] += result["original_sample_count"]
        trace = next(traces, None)
        r.require(trace is not None and key(trace) == key(raw) and trace["origin_time_ns"] == raw["origin_time_ns"], "Derivative trace identity/delay differs")
        wiring(trace["wiring"])
        for rawname, adaptedname in (("raw_native_induced_charge_fC", "induced_charge_fC"), ("raw_native_current_nA", "current_nA")):
            r.require(r.equal(trace[rawname], [-x for x in trace["trace"][adaptedname]]), "Derivative trace raw signs differ")
    r.require(next(derived, None) is None and next(traces, None) is None, "Extra derivative ledger/trace")
    expected_counts = native["counts"].copy(); expected_counts.update(counts)
    r.require(r.equal(report["counts"], expected_counts), "Derivative counts/census differ")
    factor = 1000 / native["ionisation_energy_eV"] * 1.602176634e-19; previous = None; rows = 0
    with (out / "readout-input.csv").open(encoding="utf-8", newline="") as stream:
        reader = csv.reader(stream); r.require(next(reader, None) == INPUT_HEADER, "Derivative input schema differs")
        for identity, t, q in signal_rows(modeldir / "response/signals.csv"):
            row = next(reader, None)
            r.require(row is not None and len(row) == 10 and row[:3] == list(map(str, identity)), "Derivative input identity differs")
            values = list(map(float, row[3:])); r.require(all(finite(v) for v in values), "Nonfinite derivative input")
            raw_current = 0.0 if previous is None or previous[0] != identity else (q - previous[2]) * factor / (t - previous[1]) * 1e18
            expected = [t, q, -q, q * factor * 1e15, -q * factor * 1e15, raw_current, -raw_current]
            r.require(all(math.isclose(a, b, rel_tol=1e-12, abs_tol=1e-14) for a, b in zip(values, expected, strict=True))
                      and r.equal(values[1], q) and r.equal(values[2], -q), "Fixed wiring changed a raw sample or current/charge units")
            previous = identity, t, q; rows += 1
        r.require(next(reader, None) is None and rows == native["counts"]["native_charge_samples"], "Derivative sample coverage differs")


def verify_derivative(modeldir, c, native_result, count):
    native = r.read(modeldir / "response/run.json"); out = modeldir / DERIVATIVE; report = r.read(out / "run.json")
    r.require(report["kind"] == "km_fixed_polarity_readout_derivative_v1"
              and report["status"] == ("completed_with_native_failures" if native["counts"]["native_failed_groups"] else "completed_readout_derivative")
              and report["model_id"] == MODEL and all(report[k] == 0 for k in ("native_calls", "field_calls", "radiation_calls")), "Nonterminal/non-readout KM derivative")
    r.require(report["units"] == {"time": "ns", "raw_native_equivalent_charge": "keV", "electronics_input_equivalent_charge": "keV",
              "charge": "fC", "current": "nA", "voltage": "V", "energy": "keV"}
              and r.equal(report["environment"], native["readout_environment"]), "Derivative units/pinned environment differ")
    wiring(report["wiring"]); r.verify_map(out, report["artifacts"], DERIVATIVE_ARTIFACTS)
    r.require(set(report["artifact_bytes"]) == DERIVATIVE_ARTIFACTS
              and all(r.child(out, n).stat().st_size == b for n, b in report["artifact_bytes"].items()), "Derivative artifact bytes differ")
    r.verify_map(r.ROOT / "simulation", report["source_sha256"], ("readout.jl", "readout_profiles.jl", "readout_demo.json", "Project.toml", "Manifest.toml", "ring_polarity.jl"))
    r.require(all(c["source_sha256"]["simulation/" + n] == h for n, h in report["source_sha256"].items()), "Derivative source freeze differs")
    r.require(report["source_native_report_sha256"] == native_result["native_report_sha256"]
              and report["source_ring_envelope_sha256"] == native_result["ring_response_sha256"]
              and report["source_native_ref"] == r.ref(modeldir / "response")
              and report["source_native_artifacts"] == native["artifacts"] and report["source_native_artifact_bytes"] == native["artifact_bytes"]
              and report["source_native_counts"] == native["counts"] and report["source_native_status"] == native["status"]
              and report["model_contract"] == r.read(modeldir / "response/ring-response.json")["model_contract"]
              and r.equal(report["config"], r.expected_readout(count)) and report["all_saved_successful_group_signals_covered"] is True,
              "Derivative source/config/census binding differs")
    negative_calibration(report, r.read(out / "negative-injection.json"), native)
    derivative_ledger(modeldir, report, native)
    return {"status": report["status"], "counts": report["counts"], "derivative_report_sha256": r.sha(out / "run.json"),
            "negative_injection_seconds": report["negative_injection_seconds"], "readout_derivation_seconds": report["readout_derivation_seconds"],
            "calibration": report["calibration"], "native": native_result}


def pilot_gate(directory, c):
    source = pilot_source(directory)
    r.require(r.equal(source, c["pilot_source"]), "Frozen actual pilot provenance changed")
    result = verify_derivative(model_directory(directory, "pilot"), c, source["result"], 500)
    r.require(result["status"] == "completed_readout_derivative" and result["counts"]["native_failed_groups"] == 0
              and result["counts"]["groups"] > 0 and result["counts"]["accepted"] > 0,
              "KM pilot cannot promote without clean native response and accepted fixed-wiring readout")
    return result


def stage_commands(directory, c, phase):
    modeldir = model_directory(directory, phase)
    if phase == "pilot":
        return {"derivative": derivative_command(c, modeldir)}
    return {"prepare": r.transport_command("prepare", "--model", MODEL, "--output", r.ref(modeldir / "transport"),
                    "--exporter", r.EXPORTER, "--events", "10000", "--seed", str(r.SEEDS[MODEL])),
            "transport": r.transport_command("run", "--directory", r.ref(modeldir / "transport")),
            "extract": r.transport_command("extract", "--directory", r.ref(modeldir / "transport"), "--chunk-size", "100"),
            "response": response_command(c, modeldir)}


def verify_stages(directory, c, phase):
    expected = stage_commands(directory, c, phase)
    if phase == "production":
        expected["derivative"] = derivative_command(c, model_directory(directory, phase))
    supervisor = set(); paths = []
    for stage, argv in expected.items():
        name = "km-" + phase + "-" + stage; path = directory / "km-stages" / (name + ".json"); record = r.read(path)
        r.require(record.get("test_only") is not True and record["status"] == "complete" and record["exit_code"] == 0
                  and record["name"] == name and record["command_argv"] == argv and record["source_sha256"] == c["source_sha256"]
                  and record["resource_bounds"] == c["resource_bounds"] and record["julia_threads"] == 2
                  and census_id(record["child_pid"]) > 0 and census_id(record["supervisor_pid"]) > 0, "KM actual stage provenance differs")
        supervisor.add(record["supervisor_pid"]); paths.append(path)
    r.require(len(supervisor) == 1, "KM stages have different supervisors")
    return supervisor.pop(), paths


def verify(directory, phase="pilot"):
    directory = directory_path(directory); c = configuration(directory)
    terminal_path = directory / ("km-" + phase + "-COMPLETE.json")
    r.require(terminal_path.is_file(), "KM phase has no terminal receipt; inspect existing artifacts before any rerun")
    if phase == "pilot":
        result = pilot_gate(directory, c)
    else:
        verify(directory, "pilot"); r.matching(model_directory(directory, "pilot"), model_directory(directory, "production"))
        native = verify_native(model_directory(directory, phase), 10000, "record", "all")
        result = verify_derivative(model_directory(directory, phase), c, native, 10000)
    supervisor, paths = verify_stages(directory, c, phase); terminal = r.read(terminal_path)
    expected_status = "completed_with_native_failures" if result["counts"]["native_failed_groups"] else "completed"
    r.require(terminal["status"] == expected_status and terminal["supervisor_pid"] == supervisor
              and terminal["config_sha256"] == r.sha(directory / "km-config.json") and r.equal(terminal["result"], result)
              and terminal["stage_receipt_sha256"] == {r.ref(p).removeprefix(r.ref(directory) + "/"): r.sha(p) for p in paths},
              "KM terminal result/receipt binding changed")
    name = "km-" + phase; launch = r.read(directory / (name + "-launcher.json"))
    exited = r.read(directory / (name + "-supervisor-exit.json"))
    argv = [sys.executable, "-u", "-B", str(r.ROOT / "tools/km_ring_run.py"), "run", "--directory", str(directory), "--phase", phase]
    r.require(launch["pid"] == exited["pid"] == supervisor and exited["unresolved_child_intent"] is False
              and launch["command_argv"] == argv and launch["output_root"] == r.ref(directory)
              and launch["source_sha256"] == c["source_sha256"] and launch["config_sha256"] == terminal["config_sha256"],
              "KM detached execution/clean-exit provenance differs")
    return {"status": expected_status, "result": result, "new_science_stages": 0}


def execute(directory, c, phase, stage, command):
    configuration(directory); name = "km-" + phase + "-" + stage
    target = directory / "km-stages" / (name + ".json"); logpath = target.with_suffix(".log")
    r.require(not target.exists() and not logpath.exists(), "Prior KM stage evidence exists; no uncertain rerun")
    record = {"status": "running", "name": name, "command_argv": command, "started_utc": r.utc(),
              "supervisor_pid": os.getpid(), "source_sha256": c["source_sha256"], "log": r.ref(logpath),
              "rss_scope": "Windows direct child high-water mark; WSL launcher excludes Linux descendants",
              "resource_bounds": c["resource_bounds"], "julia_threads": c["julia_threads"]}
    started = time.perf_counter(); process = None; peak = None
    environment = os.environ.copy(); environment.update(OPENBLAS_NUM_THREADS="1", OMP_NUM_THREADS="1", MKL_NUM_THREADS="1")
    try:
        with logpath.open("x", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=r.ROOT, env=environment, stdin=subprocess.DEVNULL, stdout=log,
                stderr=subprocess.STDOUT, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            record["child_pid"] = process.pid; r.atomic(target, record, fresh=True); last = 0.0
            while process.poll() is None:
                rss = r.observed_rss(process)
                if rss is not None:
                    peak = max(peak or 0, rss)
                elapsed = time.perf_counter() - started
                if elapsed - last >= 15:
                    r.atomic(directory / "km-progress.json", {"status": "running", "phase": phase, "current_stage": stage,
                        "supervisor_pid": os.getpid(), "child_pid": process.pid, "heartbeat_utc": r.utc(),
                        "stage_elapsed_seconds": elapsed, "observed_child_peak_rss_bytes": peak}); last = elapsed
                time.sleep(1)
            record["exit_code"] = process.returncode
            r.require(process.returncode == 0, "KM stage failed; preserve " + r.ref(logpath))
        configuration(directory); record["status"] = "complete"
    except BaseException as error:
        record.update(status="failed", error=str(error), child_may_be_running=process is not None and process.poll() is None)
        raise
    finally:
        record.update(finished_utc=r.utc(), elapsed_seconds=time.perf_counter() - started, observed_child_peak_rss_bytes=peak)
        r.atomic(target, record)
    return record


def run(directory, phase="pilot"):
    directory = directory_path(directory); c = configuration(directory); modeldir = model_directory(directory, phase)
    name = "km-" + phase; terminal_path = directory / (name + "-COMPLETE.json")
    if terminal_path.exists():
        return verify(directory, phase)
    idle(directory, name)
    r.require(not (directory / (name + "-supervisor-exit.json")).exists()
              and not any((directory / "km-stages").glob(name + "-*.json")), "Prior KM execution requires inspection; no rerun")
    if phase == "pilot":
        pilot_source(directory); r.require(not (modeldir / DERIVATIVE).exists(), "Saved KM derivative exists; inspect without rerunning")
    else:
        admission = verify(directory, "pilot")
        r.require(not modeldir.exists(), "Production science exists; inspect without rerunning")
    lock = directory / ".supervisor.lock"; lock.mkdir(); r.atomic(lock / "owner.json", {"pid": os.getpid(), "created_utc": r.utc(), "runner": "km_ring_run.py", "phase": phase}, fresh=True)
    started = time.perf_counter(); result = None
    try:
        r.atomic(directory / "km-progress.json", {"status": "running", "phase": phase, "supervisor_pid": os.getpid(), "started_utc": r.utc()})
        if phase == "production":
            r.atomic(directory / "km-production-admission.json", admission, fresh=True); modeldir.mkdir(parents=True)
            commands = stage_commands(directory, c, phase)
            execute(directory, c, phase, "prepare", commands["prepare"])
            r.matching(model_directory(directory, "pilot"), modeldir); verify(directory, "pilot")
            execute(directory, c, phase, "transport", commands["transport"])
            execute(directory, c, phase, "extract", commands["extract"])
            r.verify_transport(modeldir / "transport", MODEL, 10000, r.SEEDS[MODEL])
            execute(directory, c, phase, "response", commands["response"])
            native = verify_native(modeldir, 10000, "record", "all")
        else:
            native = pilot_source(directory)["result"]
        execute(directory, c, phase, "derivative", derivative_command(c, modeldir))
        result = pilot_gate(directory, c) if phase == "pilot" else verify_derivative(modeldir, c, native, 10000)
        configuration(directory); supervisor, paths = verify_stages(directory, c, phase)
        terminal = {"kind": c["kind"], "status": "completed_with_native_failures" if result["counts"]["native_failed_groups"] else "completed",
            "phase": phase, "finished_utc": r.utc(), "supervisor_pid": supervisor, "config_sha256": r.sha(directory / "km-config.json"), "result": result,
            "source_sha256": c["source_sha256"], "stage_receipt_sha256": {r.ref(p).removeprefix(r.ref(directory) + "/"): r.sha(p) for p in paths},
            "orchestration_elapsed_seconds": time.perf_counter() - started,
            "timing_scope": "Supervisor span includes checks/startup/export; native, field, radiation and derivative compute times remain separate",
            "runtime": {"supervisor_python": sys.version, "platform": platform.platform()}, "resource_bounds": c["resource_bounds"],
            "new_radiation_stages": int(phase == "production"), "new_native_stages": int(phase == "production"),
            "new_readout_derivatives": 1, "original_pilot_reruns": 0, "processing_completion_is_not_validation": True}
        r.atomic(terminal_path, terminal, fresh=True)
        r.atomic(directory / "km-progress.json", {"status": terminal["status"], "phase": phase, "result": result, "finished_utc": r.utc(), "supervisor_pid": os.getpid()})
        return terminal
    except BaseException as error:
        r.atomic(directory / "km-progress.json", {"status": "failed", "phase": phase, "error": str(error), "finished_utc": r.utc(),
            "supervisor_pid": os.getpid(), "result": result, "next_step": "Inspect exact receipts, outputs and actual workers. Preserve science; no automatic rerun."})
        raise
    finally:
        unresolved = any(r.read(p).get("child_may_be_running", False) for p in (directory / "km-stages").glob(name + "-*.json"))
        r.atomic(directory / (name + "-supervisor-exit.json"), {"pid": os.getpid(), "finished_utc": r.utc(),
            "elapsed_seconds": time.perf_counter() - started, "unresolved_child_intent": unresolved}, fresh=True)
        if not unresolved:
            (lock / "owner.json").unlink(); lock.rmdir()


def start(directory, phase="pilot"):
    directory = directory_path(directory); c = configuration(directory); name = "km-" + phase
    if (directory / (name + "-COMPLETE.json")).exists():
        return verify(directory, phase)
    r.require(os.name == "nt", "Use the existing Windows detached launcher")
    idle(directory)
    modeldir = model_directory(directory, phase)
    if phase == "pilot":
        pilot_source(directory); r.require(not (modeldir / DERIVATIVE).exists(), "Existing derivative requires inspection")
    else:
        verify(directory, "pilot"); r.require(not modeldir.exists(), "Existing production requires inspection")
    r.require(not any((directory / "km-stages").glob(name + "-*.json")), "Prior stage evidence requires inspection")
    r.require(not (directory / (name + "-supervisor-exit.json")).exists(), "Prior KM execution has exited; inspect before another launch")
    ticket = directory / (name + "-launch-ticket.json")
    r.atomic(ticket, {"created_utc": r.utc(), "intent": "one serial KM worker; duplicate launch refused", "config_sha256": r.sha(directory / "km-config.json")}, fresh=True)
    command = [sys.executable, "-u", "-B", str(r.ROOT / "tools/km_ring_run.py"), "run", "--directory", str(directory), "--phase", phase]
    logpath = directory / (name + "-supervisor.log")
    with logpath.open("x", encoding="utf-8") as log:
        process = subprocess.Popen(command, cwd=r.ROOT, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW, close_fds=True)
    launcher = {"pid": process.pid, "started_utc": r.utc(), "command_argv": command, "output_root": r.ref(directory),
                "log": r.ref(logpath), "source_sha256": c["source_sha256"], "config_sha256": r.sha(directory / "km-config.json")}
    r.atomic(directory / (name + "-launcher.json"), launcher, fresh=True)
    return launcher


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("prepare", "start", "run", "verify")); parser.add_argument("--directory", required=True)
    parser.add_argument("--phase", choices=("pilot", "production"), default="pilot"); args = parser.parse_args()
    result = prepare(args.directory) if args.command == "prepare" else globals()[args.command](args.directory, args.phase)
    print(json.dumps(result, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
