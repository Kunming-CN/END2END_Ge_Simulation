"""Saved synthetic receipts and mocked processes only; no Geant4/SSD launch."""
import copy
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

import ring_run as r

EVIDENCE = r.ROOT / ".local/ring-delivery-v1/runner-tests-v1"


def save(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def hashes(base, names):
    return {x: r.sha(base / x) for x in names}


def fixture():
    """Explicit fabricated test-only records; never eligible as actual science."""
    modeldir = EVIDENCE / "synthetic-terminal-fixture"
    transport = modeldir / "transport"; out = modeldir / "response"
    transport.mkdir(parents=True, exist_ok=True); out.mkdir(exist_ok=True)
    original = r.ROOT / ".local/ring-delivery-v1/geometry-GeRC02-corrected"
    prepared = r.read(original / "prepared.json")
    for name in prepared["files_sha256"]:
        path = transport / name; path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(original / name, path)
    prepared["primary_count"] = 500; prepared["seed"] = r.SEEDS["GeRC02"]
    prepared["source_sha256"] = hashes(r.ROOT / "transport", r.BASE_PRODUCER)
    prepared["ring_source_sha256"] = hashes(r.ROOT, r.RING_PRODUCER)
    prepared["files_sha256"] = hashes(transport, prepared["files_sha256"])
    save(transport / "prepared.json", prepared)
    save(transport / "prepare-receipt.json", {"status": "complete", "test_only": True})
    (transport / "truth.lh5").write_bytes(b"synthetic test-only placeholder, not HDF5/science\n")
    run = {"status": "complete", "returncode": 0, "test_only": True, "versions": {"remage": "1.1.0", "geant4": "11.3.2"},
           "prepared_sha256": r.sha(transport / "prepared.json"), "source_lh5_sha256": r.sha(transport / "truth.lh5"), "remage_wall_s": 1.25}
    save(transport / "run.json", run)
    stream = transport / "stream"; stream.mkdir(exist_ok=True)
    group = {"group_id": 0, "row_indices": [3], "origin_time_ns": 5.0, "horizon_ns": 100000}
    events = [{"event_id": i, "global_decay_id": i, "line_photon_count": 1, "decay_photon_count": 1,
               "steps": [{"raw_row_index": 3, "energy_keV": 100.0, "time_ns": 5.0, "position_mm": [-0.0, 0.0, 8.0]}] if i == 7 else [],
               "pulse_groups": [group] if i == 7 else []} for i in range(500)]
    chunks = []
    for start in range(0, 500, 100):
        name = "decays-%08d.jsonl" % start
        (stream / name).write_text("".join(json.dumps(e) + "\n" for e in events[start:start + 100]), encoding="utf-8")
        chunks.append({"file": name, "first_global_decay_id": start, "count": 100, "sha256": r.sha(stream / name)})
    manifest = {k: prepared[k] for k in ("model_id", "model_sha256", "model_contract", "primary_count", "coordinate_transform",
                "grouping_policy", "clock_policy", "source_sha256", "ring_source_sha256", "mounting_contract")}
    manifest.update(kind="cs137_decay_stream_v1", producer_adapter="ring_cs137_v1", status="complete", chunks=chunks,
                    global_decay_id_range=[0, 499], units={"energy": "keV", "length": "mm", "time": "ns"})
    for filename, key in (("prepared.json", "prepared_sha256"), ("run.json", "run_sha256"), ("truth.lh5", "source_lh5_sha256"),
                          ("scenario.json", "config_sha256"), ("geometry.gdml", "geometry_sha256"), ("run.mac", "macro_sha256")):
        manifest[key] = r.sha(transport / filename)
    save(stream / "manifest.json", manifest)
    (out / "truth.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events), encoding="utf-8")
    scalars = []
    for event in events:
        positive = bool(event["steps"])
        scalars.append({"record_kind": "decay", "event_id": event["event_id"], "global_decay_id": event["event_id"],
                        "raw_row_indices": [3] if positive else [], "pulse_count": int(positive), "zero_deposit": not positive,
                        "deposited_energy_keV": 100.0 if positive else 0.0})
        if positive:
            scalars.append({"record_kind": "pulse", "event_id": 7, "global_decay_id": 7, "group_id": 0,
                            "raw_row_indices": [3], "deposited_energy_keV": 100.0, "final_induced_keV": 80.0,
                            "native_max_charge_keV": 80.0, "accepted": True,
                            "readout": {"current_balance": {"passed": True}, "accepted": True, "saturated": False}})
    (out / "scalars.jsonl").write_text("".join(json.dumps(e) + "\n" for e in scalars), encoding="utf-8")
    counts = {"initial_primaries": 500, "initial_decays": 500, "zero_deposit_primaries": 499, "groups": 1,
              "accepted": 1, "rejected": 0, "readout_rejected": 0, "native_failed_groups": 0, "saturated": 0,
              "line_photons": 500, "decay_photons": 500}
    profile = r.read(r.ROOT / r.PROFILE); resolved = r.expected_readout(500)
    cal = r.read(r.ROOT / ".local/ring-delivery-v1/NATIVE-LOAD-01.log")["models"][0]["independent_calibration"]
    for name, value in (("input-contract.json", manifest), ("input-prepared.json", prepared), ("profile.json", profile),
                        ("readout-config.json", resolved), ("histograms.json", {"normalization_denominators": counts})):
        save(out / name, value)
    shutil.copyfile(r.ROOT / r.PROFILE, out / "profile-input.json")
    names = {"endpoints.csv", "endpoints.jsonl", "histograms.csv", "histograms.json", "input-contract.json", "input-prepared.json",
             "profile-input.json", "profile.json", "readout-config.json", "scalars.csv", "scalars.jsonl", "signals.csv", "summary.html", "traces.jsonl", "truth.csv", "truth.jsonl"}
    for name in names - {x.name for x in out.iterdir()}:
        (out / name).write_text("test-only fixture\n", encoding="utf-8")
    report = {"kind": "native_response_v1", "status": "completed_provisional_native_response", "test_only": True,
              "source_sha256": hashes(r.ROOT / "simulation", r.NATIVE), "artifacts": hashes(out, names),
              "artifact_bytes": {x: (out / x).stat().st_size for x in names}, "input_sha256": r.sha(stream / "manifest.json"),
              "source_lh5_sha256": run["source_lh5_sha256"], "model_sha256": prepared["model_sha256"],
              "parcels": 16, "seed_family": 2609261, "diffusion": True, "end_drift_when_no_field": False,
              "self_repulsion": False, "drift_dt_ns": 2, "nominal_drift_cap_ns": 10000, "readout_contact_id": 1,
              "temperature_K": 77, "stored_temperature_K": 78, "native_failure_policy": "abort",
              "charge_csv_policy": "examples", "bias_V": 240,
              "field_settings": {"precision_bits": 64, "min_spacing_mm": 0.05, "max_spacing_mm": 2, "sor": 1, "potential_rechecks": 4},
              "units": {"charge": "fC", "current": "nA", "voltage": "V", "energy": "keV", "time": "ns"},
              "native_failure_allowlist": ["Noncontact endpoint outside crystal", "Invalid waveform support"],
              "environment": {"environment_manifest_sha256": r.sha(r.ROOT / "simulation/Manifest.toml"), "julia_version": "1.13.0",
                              "ssd_version": "0.11.8", "project": "simulation/Project.toml", "manifest": "simulation/Manifest.toml"},
              "readout_environment": {"julia_version": "1.13.0", "pinned_julia_version": "1.13.0", "json_version": "1.9.0",
                                      "manifest_sha256": r.sha(r.ROOT / "simulation/Manifest.toml"), "project_sha256": r.sha(r.ROOT / "simulation/Project.toml")},
              "profile": profile, "profile_sha256": r.sha(r.ROOT / r.PROFILE), "config_sha256": r.sha(out / "readout-config.json"),
              "calibration": cal, "ionisation_energy_eV": 2.95, "counts": counts, "field_timings": {"test_only": 1},
              "native_drift_and_charge_seconds": 2.0, "electronics_seconds": 0.25, "process_peak_rss_bytes": 1024}
    save(out / "run.json", report)
    envelope = {"kind": "ring_native_response_v1", "status": report["status"], "model_contract": prepared["model_contract"],
                "native_report_sha256": r.sha(out / "run.json"), "new_field_solution": True, "failure_policy": "abort",
                "effective_model_sha256": prepared["model_contract"]["effective_model_sha256"], "counts": counts,
                "source_sha256": hashes(r.ROOT / "simulation", (*r.NATIVE, "ring_stream.jl", "ring_response.jl")),
                "input_sha256": report["input_sha256"], "source_model_sha256": prepared["model_sha256"],
                "profile_sha256": report["profile_sha256"], "calibration": cal}
    save(out / "ring-response.json", envelope)
    return modeldir


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.modeldir = fixture()

    def rehash(self, name, value):
        out = self.modeldir / "response"
        save(out / name, value)
        report = r.read(out / "run.json")
        report["artifacts"][name] = r.sha(out / name); report["artifact_bytes"][name] = (out / name).stat().st_size
        if name == "readout-config.json":
            report["config_sha256"] = r.sha(out / name)
        save(out / "run.json", report)
        envelope = r.read(out / "ring-response.json"); envelope["native_report_sha256"] = r.sha(out / "run.json")
        save(out / "ring-response.json", envelope)

    def test_01_saved_terminal_census_and_promotion(self):
        result = r.pilot_gate(self.modeldir, "GeRC02")
        self.assertEqual(result["counts"]["zero_deposit_primaries"], 499)
        self.assertEqual(result["positive_native_groups"], 1)

    def test_02_rehashed_readout_edit_refused(self):
        try:
            edited = r.expected_readout(500); edited["gain"] *= 2
            self.rehash("readout-config.json", edited)
            with self.assertRaisesRegex(ValueError, "beyond census"):
                r.pilot_gate(self.modeldir, "GeRC02")
        finally:
            fixture()

    def test_03_rehashed_missing_primary_refused(self):
        try:
            path = self.modeldir / "response/truth.jsonl"
            lines = path.read_text().splitlines(); lines.pop(17)
            path.write_text("\n".join(lines) + "\n")
            report = r.read(path.parent / "run.json"); report["artifacts"][path.name] = r.sha(path)
            report["artifact_bytes"][path.name] = path.stat().st_size; save(path.parent / "run.json", report)
            envelope = r.read(path.parent / "ring-response.json"); envelope["native_report_sha256"] = r.sha(path.parent / "run.json")
            save(path.parent / "ring-response.json", envelope)
            with self.assertRaisesRegex(ValueError, "Truth identity"):
                r.pilot_gate(self.modeldir, "GeRC02")
        finally:
            fixture()

    def test_04_no_positive_or_acceptance_does_not_promote(self):
        result = {"status": "completed_provisional_native_response", "counts": {"native_failed_groups": 0, "groups": 1, "accepted": 0}, "positive_native_groups": 1}
        with patch.object(r, "verify_response", return_value=result):
            with self.assertRaisesRegex(ValueError, "cannot promote"):
                r.pilot_gate(self.modeldir, "GeRC02")

    def test_05_only_census_delta(self):
        pilot = r.expected_readout(500); production = r.expected_readout(10000)
        self.assertEqual({k: v for k, v in pilot.items() if k != "expected_primary_count"},
                         {k: v for k, v in production.items() if k != "expected_primary_count"})

    def test_06_path_guards(self):
        for path in (r.ROOT, r.ROOT / ".local", r.ROOT / "docs/unsafe"):
            with self.assertRaises(ValueError):
                r.local(path)
        for name in ("../outside", "x\\unsafe", "/root/unsafe"):
            with self.assertRaises(ValueError):
                r.child(EVIDENCE, name)

    def test_07_source_freeze_and_command_bounds(self):
        deps = r.dependencies()
        self.assertIn("simulation/ring_response.jl", deps)
        command = r.transport_command("prepare", "--output", "a;touch HACK")
        self.assertIn("--locked --no-install", command[8])
        self.assertEqual(command[-1], "a;touch HACK")
        self.assertEqual(r.phase_name("pilot"), "pilot500")
        self.assertEqual(r.selected("KMRC01_candidate"), ("KMRC01_candidate",))

    def test_08_mock_process_receipt_no_science(self):
        directory = EVIDENCE / "mock-process"
        directory.mkdir(exist_ok=True); (directory / "stages").mkdir(exist_ok=True)
        name = "mock-no-science"
        # Re-running this test verifies existing evidence instead of overwriting it.
        target = directory / "stages" / (name + ".json")
        if target.exists():
            self.assertEqual(r.read(target)["exit_code"], 0)
            with patch.object(r, "config", return_value={}):
                with self.assertRaisesRegex(ValueError, "no uncertain rerun"):
                    r.execute(directory, {"source_sha256": {}}, name, ["never-run"])
            return
        class MockProcess:
            pid = 123456; returncode = 0
            def poll(self): return 0
        with patch.object(r, "config", return_value={}), patch.object(r.subprocess, "Popen", return_value=MockProcess()) as mocked:
            result = r.execute(directory, {"source_sha256": {}}, name, ["never-run"])
        self.assertEqual(mocked.call_count, 1); self.assertEqual(result["child_pid"], 123456)
        self.assertEqual(result["status"], "complete")

    def test_09_negative_zero_preserved(self):
        self.assertFalse(r.equal({"x": -0.0}, {"x": 0.0}))

    def test_10_default_phase_stops_after_pilots(self):
        directory = EVIDENCE / "mock-supervisor-pilot"
        if (directory / "pilot-both-COMPLETE.json").exists():
            result = r.read(directory / "pilot-both-COMPLETE.json")
            self.assertEqual(set(result["results"]), {"pilot500/" + x for x in r.MODELS})
            return
        directory.mkdir(exist_ok=True); (directory / "stages").mkdir(exist_ok=True)
        save(directory / "config.json", {"kind": "mock"})
        expected = {"status": "completed_provisional_native_response", "counts": {"native_failed_groups": 0}}
        with patch.object(r, "config", return_value={"kind": "mock"}), patch.object(r, "model_pipeline", return_value=expected) as pipeline:
            result = r.run(directory)
        self.assertEqual([call.args[2] for call in pipeline.call_args_list], ["pilot500", "pilot500"])
        self.assertEqual(set(result["results"]), {"pilot500/" + x for x in r.MODELS})
        self.assertFalse((directory / "production10000").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
