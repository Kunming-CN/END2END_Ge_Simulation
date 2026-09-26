"""Stdlib pipeline contract tests. Every subprocess is mocked; no radiation/SSD runs.

Fixtures are disposable under project .local and never describe numerical evidence.
Run: python -B tools/test_pipeline.py
"""
import io
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch
from html.parser import HTMLParser

sys.path.insert(0, str(Path(__file__).resolve().parent))
import pipeline_demo as p

PROJECT = p.ROOT
CONFIG = {"schema_version": 1, "expected_primary_count": None, "threshold_V": .001,
          "adc_bits": 14, "adc_full_scale_V": 10.0, "calibration_energy_keV": 500}
RUNTIME = {"julia_version": "fixture", "json_version": "fixture", "json_source_sha256": "1" * 64}
TRANSFORM = {"definition": "x_global_mm=R*x_local_mm+t",
             "rotation_local_to_global": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
             "translation_global_mm": [0, 0, 0]}


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.external_assets = []
        self.ids = set()
        self.labels = set()
        self.downloads = []
        self.embedded = ""
        self.in_data = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if "id" in attrs:
            self.ids.add(attrs["id"])
        if tag == "label":
            self.labels.add(attrs.get("for"))
        if tag in ("script", "img", "iframe", "link") and ("src" in attrs or "href" in attrs):
            self.external_assets.append(attrs)
        if tag == "a" and "download" in attrs:
            self.downloads.append(attrs["href"])
        if tag == "script" and attrs.get("id") == "pipeline-data":
            self.in_data = True

    def handle_endtag(self, tag):
        if tag == "script":
            self.in_data = False

    def handle_data(self, data):
        if self.in_data:
            self.embedded += data


class PipelineTests(unittest.TestCase):
    def setUp(self):
        (PROJECT / ".local").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(prefix="pipeline-test-", dir=PROJECT / ".local")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "student clone with spaces"
        self.root.mkdir()
        self.patch_root = patch.object(p, "ROOT", self.root)
        self.patch_root.start()
        self.addCleanup(self.patch_root.stop)
        self.output = self.root / ".local" / "example with spaces"
        for name in ("tools/pipeline_demo.py", "transport/handoff.py", "transport/run.sh",
                     "transport/pixi.toml", "transport/pixi.lock", "simulation/run.jl",
                     "simulation/replay.jl", "simulation/readout.jl", "simulation/test_readout.jl", "simulation/Project.toml",
                     "simulation/Manifest.toml", "models/catalog.json", "models/AK02.yaml", "models/SAP22.yaml"):
            file = self.root / name
            file.parent.mkdir(parents=True, exist_ok=True)
            file.write_text("mock source; no calculation\n", encoding="utf-8")
        (self.root / "simulation/Manifest.toml").write_text('julia_version = "fixture"\n', encoding="utf-8")
        (self.root / p.TEMPLATE).write_bytes((PROJECT / p.TEMPLATE).read_bytes())
        self.write(self.root / "simulation/readout_demo.json", CONFIG)
        self.count = 4
        self.fail_stage = None
        self.calls = []

    @staticmethod
    def write(path, value):
        path.write_text(p.json_text(value), encoding="utf-8")

    def fake_subprocess(self, command, *, cwd, stdout, stderr, check, shell):
        self.assertEqual(cwd, self.root)
        self.assertEqual(stderr, subprocess.STDOUT)
        self.assertTrue(check)
        self.assertFalse(shell)
        self.assertIsInstance(command, list)
        self.calls.append(command)
        log = Path(stdout.name)
        stage = log.stem
        if stage == self.fail_stage:
            stdout.write(b"mock child failure; local diagnostic\n")
            raise subprocess.CalledProcessError(17, command)
        if stage == "wslpath":
            stdout.write(b"/mnt/c/student clone with spaces\n")
            return subprocess.CompletedProcess(command, 0)
        if stage == "julia_environment":
            stdout.write(("mock startup diagnostic\nPIPELINE_RUNTIME_JSON=" + json.dumps(RUNTIME) + "\n").encode("utf-8"))
            return subprocess.CompletedProcess(command, 0)
        stdout.write(b"mock fixture only, not a physical simulation\n")
        model = log.parent.name
        base = self.output / model
        getattr(self, "fixture_" + stage)(base, model)
        return subprocess.CompletedProcess(command, 0)

    def fixture_prepare(self, base, model):
        directory = base / "transport"
        directory.mkdir()
        for name in ("geometry.gdml", "run.mac", "probe-points.txt"):
            (directory / name).write_text("mock fixture\n", encoding="utf-8")
        doc = {"model_id": model, "model_sha256": p.sha256(self.root / f"models/{model}.yaml"),
               "primary_count": self.count, "seed": 260926, "energy_keV": 662,
               "coordinate_transform": TRANSFORM, "stored_contact_potentials_V": [0, 500 if model == "AK02" else 700],
               "contour_rz_mm": [[0, 0], [12, 0], [12, 10], [0, 10], [0, 0]],
               "files_sha256": {n: p.sha256(directory / n) for n in ("geometry.gdml", "run.mac", "probe-points.txt")}}
        self.write(directory / "prepared.json", doc)

    def fixture_transport(self, base, model):
        directory = base / "transport"
        (directory / "truth.lh5").write_bytes(b"mock LH5 never parsed or advertised as simulation")
        self.write(directory / "run.json", {"status": "complete", "prepared_sha256": p.sha256(directory / "prepared.json"),
                                            "source_lh5_sha256": p.sha256(directory / "truth.lh5")})

    def fixture_extract(self, base, model):
        directory = base / "transport"
        prep = p.load_json(directory / "prepared.json")
        events, row = [], 0
        for i in range(self.count):
            steps = []
            if i % 4:
                steps = [{"raw_row_index": row, "energy_keV": 100.0, "time_ns": 0.0,
                          "position_mm": [10, 0, 5], "global_position_m": [.010, 0, .005],
                          "pre_position_mm": [10, 0, 5], "post_position_mm": [10, 0, 5],
                          "track_id": 1, "parent_track_id": 0, "particle_pdg": 22}]
                row += 1
            events.append({"event_id": i, "primary_time_ns": 0.0, "steps": steps})
        self.write(directory / "events.json", {"schema_version": 1, "model_id": model, "model_sha256": prep["model_sha256"],
                   "primary_count": self.count, "events": events, "energy_sum_keV": row * 100.0,
                   "coordinate_transform": TRANSFORM, "source_lh5_sha256": p.sha256(directory / "truth.lh5"),
                   "geometry_sha256": p.sha256(directory / "geometry.gdml"), "macro_sha256": p.sha256(directory / "run.mac"),
                   "provenance": {"prepared_sha256": p.sha256(directory / "prepared.json"), "run_sha256": p.sha256(directory / "run.json"),
                                  "seed": 260926, "extractor_versions": {"python": "fixture"},
                                  "lock_sha256": p.sha256(self.root / "transport/pixi.lock"),
                                  "versions": {"remage": "fixture", "geant4": "fixture"}}})

    def fixture_charge(self, base, model):
        directory = base / "charge"
        directory.mkdir()
        truth = p.load_json(base / "transport/events.json")
        statuses = ["zero_deposit", "stopped_without_contact", "completed", "step_limit"]
        events = []
        csv = ["event_id,time_since_primary_ns,induced_equivalent_energy_keV"]
        for t in truth["events"]:
            i = t["event_id"]
            energy = sum(s["energy_keV"] for s in t["steps"])
            status, final = statuses[i % 4], energy * .8
            events.append({"event_id": i, "status": status, "deposited_energy_keV": energy,
                           "final_induced_equivalent_energy_keV": final, "samples": 2, "time_since_primary_end_ns": 2,
                           "steps": [{"raw_row_index": s["raw_row_index"], "endpoints": [{"status": status, "step_limit_reached": status == "step_limit"}]} for s in t["steps"]]})
            csv += [f"{i},0,0", f"{i},2,{final}"]
        (directory / "signals.csv").write_text("\n".join(csv) + "\n", encoding="utf-8")
        self.write(directory / "run.json", {"model_id": model, "model_sha256": truth["model_sha256"],
                   "status": "completed_with_transport_flags", "events": events, "primary_count": self.count,
                   "selected_primary_count": self.count, "unselected_event_ids": [], "effective_temperature_K": 77,
                   "contact_potentials_V": [0, 500 if model == "AK02" else 700], "ionisation_energy_eV": 2.95,
                   "geometry": {"ssd_contour_matches": True}, "input_sha256": p.sha256(base / "transport/events.json"),
                   "source_lh5_sha256": truth["source_lh5_sha256"], "source_provenance": truth["provenance"],
                   "time_step_ns": 2, "environment_manifest_sha256": p.sha256(self.root / "simulation/Manifest.toml"),
                   "source_code_sha256": {n: p.sha256(self.root / "simulation" / n) for n in ("run.jl", "replay.jl")},
                   "julia_version": "fixture", "ssd_version": "fixture", "timings": {"potential_seconds": .01}, "runtime_seconds": .02})

    def fixture_readout(self, base, model):
        directory = base / "readout"
        directory.mkdir()
        charge = p.load_json(base / "charge/run.json")
        events = []
        for c in charge["events"]:
            i = c["event_id"]
            peak = [0, .08, .5, 11][i % 4]
            code = min(16383, int(peak / (10 / 16384)))
            accepted = 0 < peak < 10
            q = c["final_induced_equivalent_energy_keV"] * 1000 / 2.95 * 1.602176634e-4
            events.append({"event_id": i, "deposited_energy_keV": c["deposited_energy_keV"],
                           "final_induced_equivalent_energy_keV": c["final_induced_equivalent_energy_keV"],
                           "charge_status": c["status"], "peak_V": peak, "peak_time_ns": 4, "adc_code": code,
                           "reconstructed_energy_keV": (code + .5) * (10 / 16384) / .001 if accepted else None,
                           "accepted": accepted, "rejection_reason": None if accepted else "below_threshold" if peak == 0 else "saturated",
                           "flags": {"charge_status": c["status"], "steps": c["steps"]},
                           "input_sample_count": 2, "original_sample_count": 4, "readout_end_ns": 6,
                           "charge_end_ns": 2, "tail_window_ns": 4, "negative_input": False,
                           "saturated": peak >= 10, "window_limited": False, "peak_at_window_end": False,
                           "analog_energy_keV": peak / .001, "adc_midpoint_V": (code + .5) * (10 / 16384),
                           "final_charge_C": q * 1e-15, "trace_preserves_all_current_runs": True,
                           "current_balance": {"integrated_current_C": q * 1e-15, "charge_change_C": q * 1e-15,
                                               "residual_C": 0.0, "tolerance_C": 1e-28, "passed": True},
                           "trace": {"time_ns": [0, 2, 4, 6], "induced_charge_fC": [0, q, q, q],
                                     "current_bin_start_ns": [0, 0, 2, 4], "current_bin_end_ns": [0, 2, 4, 6],
                                     "current_nA": [0, q * 500, 0, 0], "preamp_V": [0, -peak / 2, -peak / 3, -peak / 4],
                                     "shaped_V": [0, peak / 2, peak, peak / 2]}})
        summary = p.event_summary(events)
        provenance = {key: p.sha256(base / name) for key, name in {
            "charge_run_sha256": "charge/run.json", "signals_sha256": "charge/signals.csv",
            "truth_sha256": "transport/events.json", "source_lh5_sha256": "transport/truth.lh5",
            "geometry_sha256": "transport/geometry.gdml", "macro_sha256": "transport/run.mac",
            "prepared_sha256": "transport/prepared.json", "transport_run_sha256": "transport/run.json"}.items()}
        provenance.update({key: p.sha256(self.root / name) for key, name in {
            "model_sha256": f"models/{model}.yaml", "config_sha256": "simulation/readout_demo.json",
            "readout_source_sha256": "simulation/readout.jl", "manifest_sha256": "simulation/Manifest.toml",
            "model_catalog_sha256": "models/catalog.json", "charge_manifest_sha256": "simulation/Manifest.toml"}.items()})
        provenance["test_source_sha256"] = p.sha256(self.root / "simulation/test_readout.jl")
        provenance["readout_environment"] = dict(RUNTIME, project="simulation/Project.toml", manifest="simulation/Manifest.toml",
            project_sha256=p.sha256(self.root / "simulation/Project.toml"), manifest_sha256=p.sha256(self.root / "simulation/Manifest.toml"), pinned_julia_version="fixture")
        truth = p.load_json(base / "transport/events.json")
        provenance["transport"] = {k: truth["provenance"][k] for k in ("seed", "versions", "extractor_versions", "lock_sha256")}
        provenance["charge_versions"] = {"julia": charge["julia_version"], "ssd": charge["ssd_version"]}
        provenance["charge_source_sha256"] = charge["source_code_sha256"]
        self.write(directory / "run.json", {"schema_version": 1, "model_id": model, "status": "completed", "events": events,
                   "config": CONFIG, "calibration": {"volts_per_keV": .001, "adc_lsb_V": 10 / 16384,
                                                       "method": "single delta-charge injection at t=0; sampled analog peak; fixed across events",
                                                       "adc_convention": "floor(V/LSB); reconstruct (code+0.5)*LSB; threshold inclusive; saturation at V>=10 V",
                                                       "charge_C": 500 * 1000 / 2.95 * 1.602176634e-19,
                                                       "time_step_ns": 2, "peak_time_ns": 4, "adc_half_lsb_energy_keV": (10 / 16384) / 2 / .001,
                                                       "peak_V": .5, "energy_keV": 500, "ionisation_energy_eV": 2.95},
                   "provenance": provenance, "unselected_event_ids": [], "readout_contact_id": 1, "json_version": "fixture", "julia_version": "fixture", "pinned_julia_version": "fixture",
                   "supported_waveform_policy": "Reject any negative cumulative Q without rectification",
                   "trace_current_convention": "Original bins, not display gaps",
                   "time_step_ns": 2, "polarity": "positive induced charge gives negative CSA; shaped=-gain*r2",
                   "time_origin": "time since each primary; numerical analog grid, not waveform ADC",
                   "units": {"time": "ns", "charge": "fC", "current": "nA", "voltage": "V", "energy": "keV"},
                   "summary": {"primary_count": self.count, "selected_primary_count": self.count,
                               "accepted_count": summary["accepted"], "rejected_count": self.count - summary["accepted"],
                               "zero_deposit_count": summary["zero_deposit"], "transport_flagged_count": summary["flagged"],
                               "total_original_samples": 4 * self.count}, "limitations": ["MOCK DATA — never simulation evidence"]})
        for name in ("events.csv", "spectrum.csv"):
            (directory / name).write_text("mock table\n", encoding="utf-8")

    def run_fixture(self, *, model=None):
        with patch.object(p.subprocess, "run", self.fake_subprocess), patch.dict(os.environ, {"JULIA_EXECUTABLE": "C:/runtime with spaces/julia.exe"}):
            return p.run_pipeline(self.output, events=self.count, model=model)

    def reseal(self):
        """Exercise semantic validation independently of the outer checksum gate."""
        manifest = p.load_json(self.output / "run.json")
        manifest["artifacts"] = p.inventory(self.output)
        for stage in manifest["stages"]:
            stage["output_artifacts"] = {k: manifest["artifacts"].get(k, v) for k, v in stage["output_artifacts"].items()}
        p.seal_manifest(manifest)
        self.write(self.output / "run.json", manifest)

    def mutate_readout(self, change):
        path = self.output / "AK02/readout/run.json"
        data = p.load_json(path)
        change(data)
        self.write(path, data)
        self.reseal()

    def test_protected_paths_and_overwrite(self):
        for bad in (self.root, self.root / ".local", self.root / "docs/new", ".local/../../escape"):
            with self.subTest(path=str(bad)), self.assertRaisesRegex(ValueError, "below project .local"):
                p.local_path(bad, new=True)
        self.output.mkdir(parents=True)
        (self.output / "keep").write_text("original")
        with self.assertRaisesRegex(ValueError, "already exists"):
            p.run_pipeline(self.output)
        self.assertEqual((self.output / "keep").read_text(), "original")

    def test_reparse_points_rejected_on_python310(self):
        fake = types.SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
        with patch.object(Path, "lstat", return_value=fake), self.assertRaisesRegex(ValueError, "reparse"):
            p.no_links(self.output)

    def test_symlink_rejected(self):
        target = self.root / ".local/target"
        target.mkdir(parents=True)
        link = self.root / ".local/link"
        try:
            link.symlink_to(target, target_is_directory=True)
        except OSError:
            self.skipTest("OS does not permit creating test symlinks; reparse guard separately tested")
        with self.assertRaisesRegex(ValueError, "symlink"):
            p.local_path(link / "new")

    def test_argument_arrays_preserve_spaces(self):
        commands = dict(p.commands_for("AK02", self.output, 100, 260926, 662, "C:/Julia installation/julia.exe", "/mnt/c/student clone with spaces"))
        prep = commands["prepare"]
        self.assertEqual(prep[:6], ["wsl.exe", "--distribution", "Ubuntu-24.04", "--exec", "bash", "/mnt/c/student clone with spaces/transport/run.sh"])
        self.assertIn("-B", prep)
        self.assertEqual(commands["transport"][-2], "--directory")
        self.assertNotIn("-c", prep)
        self.assertEqual(commands["charge"][0], "C:/Julia installation/julia.exe")
        self.assertIn("--project=" + str(self.root / "simulation"), commands["charge"])
        self.assertEqual(commands["charge"][-2:], ["--temperature-k", "77"])
        portable = p.portable_command(commands["charge"], self.output)
        self.assertEqual(portable[0], "julia.exe")
        self.assertIn("{RUN}/AK02/transport/events.json", portable)
        self.assertNotIn(str(self.root), json.dumps(portable))
        linux = dict(p.commands_for("SAP22", self.output, 1, 2, 3, "/opt/julia/julia"))
        self.assertEqual(linux["prepare"][0], "bash")
        self.assertEqual(linux["prepare"][1], self.root.as_posix() + "/transport/run.sh")

    def test_failure_manifest_and_logs(self):
        self.fail_stage = "transport"
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_fixture()
        m = p.load_json(self.output / "run.json")
        self.assertEqual(m["status"], "failed")
        self.assertEqual(m["failure"]["stage"], "transport")
        self.assertEqual(m["stages"][-1]["status"], "failed")
        self.assertEqual(m["stages"][-1]["returncode"], 17)
        self.assertIn("AK02/transport.log", m["artifacts"])
        self.assertFalse((self.output / "SAP22").exists())
        p.check_seal(m, "manifest_sha256")
        with self.assertRaisesRegex(ValueError, "incomplete"):
            p.export_run(self.output, self.root / ".local/export")

    def test_preflight_failure_recorded_without_running(self):
        with patch.dict(os.environ, {"JULIA_EXECUTABLE": ""}), patch.object(p.shutil, "which", return_value=None):
            with self.assertRaisesRegex(ValueError, "Julia missing"):
                p.run_pipeline(self.output, events=self.count)
        m = p.load_json(self.output / "run.json")
        self.assertEqual(m["failure"]["stage"], "preflight")
        self.assertEqual(m["stages"], [])

    def test_both_models_complete_all_100(self):
        self.count = 100
        manifest = self.run_fixture()
        checked, models = p.validate_run(self.output)
        self.assertEqual(checked, manifest)
        self.assertEqual(len(manifest["event_keys"]), 200)
        self.assertEqual(len(set(manifest["event_keys"])), 200)
        for model in models:
            self.assertEqual([e["event_id"] for e in model["events"]], list(range(100)))
            self.assertEqual(model["summary"]["accepted"], 50)
            self.assertEqual(model["summary"]["zero_deposit"], 25)
            self.assertEqual(model["summary"]["flagged"], 50)
            self.assertEqual(model["summary"]["saturated"], 25)
        self.assertNotIn("run.json", manifest["artifacts"])
        self.assertIn("AK02/charge/run.json", manifest["artifacts"])

    def test_single_model(self):
        manifest = self.run_fixture(model="SAP22")
        self.assertEqual(manifest["models"], ["SAP22"])
        self.assertFalse((self.output / "AK02").exists())
        p.validate_run(self.output)

    def test_changed_every_relevant_artifact_rejected(self):
        self.run_fixture()
        for rel in ("AK02/transport/events.json", "AK02/transport/truth.lh5", "AK02/charge/signals.csv", "AK02/charge/run.json", "AK02/readout/run.json", "AK02/readout/events.csv", "AK02/readout/spectrum.csv"):
            path = self.output / rel
            original = path.read_bytes()
            path.write_bytes(original + b" ")
            with self.subTest(file=rel), self.assertRaisesRegex(ValueError, "artifact inventory/hash"):
                p.validate_run(self.output)
            path.write_bytes(original)
        config = self.root / "simulation/readout_demo.json"
        config.write_text(config.read_text() + " ")
        with self.assertRaisesRegex(ValueError, "input/source hash"):
            p.validate_run(self.output)

    def test_missing_id_cannot_be_hidden_by_resealing(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"].pop(0))
        with self.assertRaisesRegex(ValueError, "missing/duplicate/reordered"):
            p.validate_run(self.output)

    def test_missing_signal_id(self):
        self.run_fixture()
        path = self.output / "AK02/charge/signals.csv"
        path.write_text("\n".join(line for line in path.read_text().splitlines() if not line.startswith("0,")) + "\n")
        reports = p.load_json(self.output / "AK02/charge/run.json")["events"]
        with self.assertRaisesRegex(ValueError, "missing/mixed"):
            p.validate_signals(path, reports)

    def test_readout_summary_counts_checked(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["summary"].update(accepted_count=999))
        with self.assertRaisesRegex(ValueError, "summary/selection"):
            p.validate_run(self.output)

    def test_energy_ledger_checked(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1].update(deposited_energy_keV=101))
        with self.assertRaisesRegex(ValueError, "energy ledger"):
            p.validate_run(self.output)

    def test_endpoint_flags_checked(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1]["flags"].update(steps=[]))
        with self.assertRaisesRegex(ValueError, "endpoint flags lost"):
            p.validate_run(self.output)

    def test_adc_calibration_checked(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1].update(reconstructed_energy_keV=123))
        with self.assertRaisesRegex(ValueError, "reconstructed energy/calibration"):
            p.validate_run(self.output)

    def test_exact_peak_required(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1].update(peak_time_ns=3))
        with self.assertRaisesRegex(ValueError, "exact peak sample absent"):
            p.validate_run(self.output)

    def test_explicit_completed_status_required(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d.pop("status"))
        with self.assertRaisesRegex(ValueError, "explicit completed status"):
            p.validate_run(self.output)

    def test_legacy_flag_list_rejected(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1].update(flags=[]))
        with self.assertRaisesRegex(ValueError, "flags DICT"):
            p.validate_run(self.output)

    def test_calibration_identity_across_models_and_root(self):
        manifest = self.run_fixture()
        self.assertEqual(manifest["calibration_sha256"], p.digest(manifest["calibration_identity"]))
        path = self.output / "SAP22/readout/run.json"
        data = p.load_json(path)
        data["calibration"]["peak_time_ns"] = 6
        self.write(path, data)
        self.reseal()
        with self.assertRaisesRegex(ValueError, "calibration identity differs across models"):
            p.validate_run(self.output)

    def test_all_provenance_fields_bound(self):
        self.run_fixture()
        path = self.output / "AK02/readout/run.json"
        original = p.load_json(path)
        for key in original["provenance"]:
            with self.subTest(key=key):
                self.write(path, original)
                self.mutate_readout(lambda d: d["provenance"].update({key: "0" * 64}))
                with self.assertRaisesRegex(ValueError, "readout provenance mismatch"):
                    p.validate_run(self.output)

    def test_charge_sourcecode_hash_bound(self):
        self.run_fixture()
        path = self.output / "AK02/charge/run.json"
        charge = p.load_json(path)
        charge["source_code_sha256"]["replay.jl"] = "0" * 64
        self.write(path, charge)
        self.reseal()
        with self.assertRaisesRegex(ValueError, "charge sourcecode"):
            p.validate_run(self.output)

    def test_adc_mutations_and_zero_null(self):
        self.run_fixture()
        path = self.output / "AK02/readout/run.json"
        original = p.load_json(path)
        cases = [(1, {"adc_code": 5}, "ADC code"),
                 (0, {"reconstructed_energy_keV": 0}, "energy inconsistency"),
                 (0, {"accepted": True, "rejection_reason": None}, "threshold/rejection"),
                 (3, {"saturated": False}, "saturation flag"),
                 (1, {"negative_input": True}, "negative cumulative"),
                 (1, {"analog_energy_keV": 123}, "analog energy"),
                 (1, {"peak_at_window_end": True}, "window flag")]
        for i, values, message in cases:
            with self.subTest(values=values):
                self.write(path, original)
                self.mutate_readout(lambda d: d["events"][i].update(values))
                with self.assertRaisesRegex(ValueError, message):
                    p.validate_run(self.output)

    def test_joint_endpoint_flags_union(self):
        self.run_fixture()
        base = self.output / "AK02"
        charge = p.load_json(base / "charge/run.json")
        charge["events"][3]["steps"][0]["endpoints"].append(
            {"status": "stopped_without_contact", "step_limit_reached": False, "retained_detail": [1, 2, 3]})
        self.write(base / "charge/run.json", charge)
        readout = p.load_json(base / "readout/run.json")
        readout["events"][3]["flags"]["steps"] = charge["events"][3]["steps"]
        readout["provenance"]["charge_run_sha256"] = p.sha256(base / "charge/run.json")
        self.write(base / "readout/run.json", readout)
        self.reseal()
        _, models = p.validate_run(self.output)
        summary = models[0]["summary"]
        self.assertEqual((summary["step_limit"], summary["stopped_without_contact"], summary["flagged"]), (1, 2, 2))
        event = models[0]["events"][3]
        self.assertTrue(event["has_step_limit"] and event["has_stopped_without_contact"])
        self.assertEqual(event["flags"], readout["events"][3]["flags"])

    def test_fixed_census_fails_before_subprocess(self):
        self.write(self.root / "simulation/readout_demo.json", dict(CONFIG, expected_primary_count=100))
        with patch.object(p.subprocess, "run") as child, self.assertRaisesRegex(ValueError, "primary count"):
            p.run_pipeline(self.output, events=4)
        child.assert_not_called()

    def test_original_current_bins_and_charge_endpoint_required(self):
        self.run_fixture()
        self.mutate_readout(lambda d: d["events"][1]["trace"]["current_bin_start_ns"].__setitem__(2, 0))
        with self.assertRaisesRegex(ValueError, "current bin start mismatch"):
            p.validate_run(self.output)

    def test_offline_export_escaping_and_placeholders(self):
        self.run_fixture()
        output = self.root / ".local/export"
        dangerous = "</ScRiPt><script>alert('test')</script><!-- & <"
        with patch.object(p, "LIMITATIONS", [dangerous]):
            data = p.export_run(self.output, output)
        html = (output / "pipeline.html").read_text(encoding="utf-8")
        self.assertNotIn(dangerous, html)
        self.assertNotIn(p.TOKEN, html)
        self.assertNotIn("fetch(", html)
        self.assertNotIn("XMLHttpRequest", html)
        self.assertNotIn("@import", html)
        self.assertIn("currentBins(e,chargeWindow)", html)
        self.assertIn("current_bin_start_ns", html)
        self.assertIn("Do not integrate between decimated display points", html)
        self.assertIn("e.input_sample_count", html)
        self.assertNotIn(str(self.root), html)
        parser = PageParser()
        parser.feed(html)
        self.assertEqual(parser.external_assets, [])
        self.assertEqual(parser.downloads, ["data.json"])
        self.assertTrue({"model-select", "event-select"} <= parser.labels)
        self.assertEqual(json.loads(parser.embedded), data)
        self.assertEqual(p.validate_export(output), data)
        self.assertEqual(sorted(x.name for x in output.iterdir()), ["data.json", "pipeline.html"])
        with self.assertRaisesRegex(ValueError, "already exists"):
            p.export_run(self.output, output)

    def test_export_deterministic_and_tamper_evident(self):
        self.run_fixture()
        first, second = self.root / ".local/export1", self.root / ".local/export2"
        p.export_run(self.output, first)
        p.export_run(self.output, second)
        for name in ("data.json", "pipeline.html"):
            self.assertEqual((first / name).read_bytes(), (second / name).read_bytes())
        (first / "pipeline.html").write_bytes((first / "pipeline.html").read_bytes() + b" ")
        with self.assertRaisesRegex(ValueError, "differs from verified"):
            p.validate_export(first)
        (second / "extra.txt").write_text("not allowed")
        with self.assertRaisesRegex(ValueError, "exactly"):
            p.validate_export(second)

    def test_public_summary_cannot_hide_selection(self):
        self.run_fixture()
        output = self.root / ".local/export"
        data = p.export_run(self.output, output)
        data["models"][0]["summary"]["primaries"] = 3
        data.pop("export_sha256")
        data["export_sha256"] = p.digest(data)
        (output / "data.json").write_bytes(p.json_text(data).encode("utf-8"))
        (output / "pipeline.html").write_bytes(p.render_html(data).encode("utf-8"))
        with self.assertRaisesRegex(ValueError, "summary/selection"):
            p.validate_export(output)

    def test_public_paths_and_inventory_traversal(self):
        for text in ("C:/Users/private/file", "C:\\Users\\private\\file", "/home/owner/file", "file:///private/file"):
            with self.assertRaisesRegex(ValueError, "private absolute path"):
                p.check_public({"metadata": [text]})
        for name in ("../escape", "/escape", "C:/escape", "a\\b", "a/../b", "./a"):
            with self.assertRaises(ValueError):
                p.relative_file(self.output, name)

    def test_cli_defaults_and_failure_exit(self):
        with patch.object(p, "run_pipeline", return_value={"run_id": "fixture"}) as run, patch("sys.stdout", new_callable=io.StringIO):
            self.assertEqual(p.main(["run", "--output", ".local/new"]), 0)
            run.assert_called_once_with(".local/new", 100, 260926, 662, None)
        with patch.object(p, "export_run", side_effect=ValueError("changed input")), patch("sys.stderr", new_callable=io.StringIO) as err:
            self.assertEqual(p.main(["export", "--input", ".local/old", "--output", ".local/new"]), 1)
            self.assertIn("changed input", err.getvalue())


if __name__ == "__main__":
    unittest.main(verbosity=2)
