"""Small source-only fixtures; no transport, fields, native response or installs.

Run with the existing Python and --evidence a NEW project-local evidence folder.
All fixtures, subprocess commands, return codes and logs are retained.
"""
import argparse
import copy
import hashlib
import json
import shutil
import subprocess
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = (
    "Run.cmd", "tools/scenario_cli.ps1", "tools/electronics_settings.ps1",
    "tools/native_run_validation.ps1", "tools/run_native_campaign.ps1",
    "simulation/readout_profiles.jl", "simulation/readout.jl",
    "simulation/Project.toml", "simulation/Manifest.toml",
    "simulation/readout_demo.json", "simulation/native_readout_profile.json",
)
EVIDENCE = None


def psquote(value):
    return "'" + str(value).replace("'", "''") + "'"


def snapshot(root):
    return {str(p.relative_to(root)): (hashlib.sha256(p.read_bytes()).hexdigest(),
                                      p.stat().st_size, p.stat().st_mtime_ns)
            for p in root.rglob("*") if p.is_file() and not p.is_symlink()}


class ElectronicsSettings(unittest.TestCase):
    def setUp(self):
        self.home = EVIDENCE / self.id().split(".")[-1]
        self.root = self.home / "root"
        self.root.mkdir(parents=True)
        for rel in FILES:
            dest = self.root / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / rel, dest)
        self.original = json.loads((self.root / FILES[-1]).read_text())
        self.base = json.loads((self.root / "simulation/readout_demo.json").read_text())
        self.seq = 0

    def invoke(self, *arguments, ok=True, stdin=None, script="tools/scenario_cli.ps1"):
        self.seq += 1
        expr = "& " + psquote(self.root / script)
        for arg in arguments:
            expr += " " + (arg if arg.startswith("-") and not arg.startswith("-{") else psquote(arg))
        command = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", expr]
        done = subprocess.run(command, cwd=self.root, input=stdin, capture_output=True,
                              text=True, timeout=25)
        record = {"command": command, "cwd": str(self.root), "exit_code": done.returncode,
                  "stdout": done.stdout, "stderr": done.stderr}
        (self.home / f"command-{self.seq:03d}.json").write_text(json.dumps(record, indent=2), encoding="utf-8")
        if ok:
            self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
        else:
            self.assertNotEqual(done.returncode, 0, done.stdout + done.stderr)
        return done

    def setting(self, mode, *arguments, ok=True):
        result = self.invoke("settings", mode, *arguments, "-Json", ok=ok)
        return json.loads(result.stdout) if ok else result

    def put(self, name, data):
        target = self.root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return name

    def expected(self, profile):
        independent = copy.deepcopy(self.base)
        del independent["max_total_samples"]
        independent.update(profile["settings"])
        independent.update(schema_version=2, expected_primary_count=None)
        return independent

    def test_default_roundtrip_idempotent_no_overwrite(self):
        shown = self.setting("show")
        self.assertEqual(shown["profile"], self.original)
        self.assertEqual(shown["configuration"], self.expected(self.original))
        self.assertEqual(shown["configuration"]["shaping_tau_us"], 0.5)
        saved = self.setting("save", "-SaveName", "one")
        checked = self.setting("check", "-SettingsFile", saved["saved_path"])
        second = self.setting("save", "-SaveName", "two", "-SettingsFile", saved["saved_path"])
        for candidate in (saved, checked, second):
            self.assertEqual(candidate["physics_sha256"], shown["physics_sha256"])
            self.assertEqual(candidate["configuration"], shown["configuration"])
        before = snapshot(self.root)
        self.setting("save", "-SaveName", "one", ok=False)
        self.assertEqual(snapshot(self.root), before)
        bundle = json.loads((self.root / second["saved_path"]).read_text())
        self.assertEqual(bundle["revision"], 1)
        self.assertEqual(bundle["profile"]["name"], "two")
        self.assertEqual(bundle["provenance"]["input"]["path"], saved["saved_path"])

    def test_every_setting_reaches_independent_full_configuration(self):
        default = self.setting("show")
        edits = {"feedback_capacitance_pF": 0.8, "feedback_tau_us": 40,
                 "pole_zero_tau_us": 30, "shaping_tau_us": 0.8, "gain": 10,
                 "adc_bits": 12, "adc_full_scale_V": 4, "threshold_V": 0.002,
                 "peak_policy": "legacy_reject_negative_input"}
        patches = [{k: v} for k, v in edits.items()]
        patches += [{"peak_gate_start_ns": 0, "peak_gate_end_ns": 99998},
                    {"peak_gate_start_ns": 100, "peak_gate_end_ns": 90000}]
        for index, patch in enumerate(patches):
            with self.subTest(patch=patch):
                changed = self.setting("save", "-SaveName", f"edit{index}", "-SetJson", json.dumps(patch))
                independently_edited = copy.deepcopy(self.original)
                independently_edited["settings"].update(patch)
                self.assertEqual(changed["configuration"], self.expected(independently_edited))
                self.assertNotEqual(changed["physics_sha256"], default["physics_sha256"])
                self.setting("check", "-SettingsFile", changed["saved_path"])

    def test_simple_edit_preserves_advanced_and_inherited(self):
        changed = self.setting("save", "-SaveName", "advanced", "-SetJson", json.dumps({
            "feedback_tau_us": 42, "pole_zero_tau_us": 37,
            "peak_gate_start_ns": 2, "peak_gate_end_ns": 90000}))
        simple = self.setting("save", "-SaveName", "simple", "-SettingsFile", changed["saved_path"],
                              "-SetJson", '{"gain":12}')
        wanted = copy.deepcopy(changed["configuration"])
        wanted["gain"] = 12
        self.assertEqual(simple["configuration"], wanted)

    def test_unknown_missing_fields_and_unexpected_kinds(self):
        variants = []
        for key in ("schema_version", "kind", "name", "settings"):
            bad = copy.deepcopy(self.original); del bad[key]; variants.append(bad)
        for key in self.original["settings"]:
            bad = copy.deepcopy(self.original); del bad["settings"][key]; variants.append(bad)
        for key, value in (("extra", 1), ("kind", "other"), ("schema_version", True),
                           ("schema_version", 2.0), ("name", "../bad"), ("settings", [])):
            bad = copy.deepcopy(self.original); bad[key] = value; variants.append(bad)
        bad = copy.deepcopy(self.original); bad["settings"]["sampling_frequency_Hz"] = 1; variants.append(bad)
        for index, data in enumerate(variants):
            with self.subTest(index=index):
                rel = self.put(f"inputs/bad{index}.json", data)
                self.setting("check", "-SettingsFile", rel, ok=False)
        self.setting("check", "-SetJson", '{"Gain":20}', ok=False)
        self.assertFalse((self.root / ".local").exists())

    def test_invalid_types_combinations_nonfinite(self):
        edits = [{"gain": v} for v in (True, False, None, "20", [], {}, 0, -1, float("nan"), float("inf"))]
        edits += [{"adc_bits": v} for v in (True, 14.0, 1, 25, "14")]
        edits += [{"threshold_V": v} for v in (0, -1, 10, 11)]
        edits += [{"peak_policy": v} for v in (True, 0, [], "rectify", "SIGNED_INPUT_POSITIVE_PEAK")]
        edits += [{"peak_gate_start_ns": 0}, {"peak_gate_end_ns": 3},
                  {"peak_gate_start_ns": 4, "peak_gate_end_ns": 4},
                  {"peak_gate_start_ns": -1, "peak_gate_end_ns": 3},
                  {"peak_gate_start_ns": 0, "peak_gate_end_ns": 99999},
                  {"peak_gate_start_ns": False, "peak_gate_end_ns": 3}]
        before = snapshot(self.root)
        for edit in edits:
            with self.subTest(edit=edit):
                self.setting("save", "-SaveName", "invalid", "-SetJson", json.dumps(edit), ok=False)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".local").exists())

    def test_strict_json_duplicates_and_overflow(self):
        for patch in ('{"gain":1,"gain":2}', '{"gain":1,"Gain":2}', '{"gain":1,}',
                      '{"gain":1e999}', '{"gain":01}', '{"gain":2} trailing',
                      '{"gain":2 // comment\n}', '{"gain":2,"ga\\u0069n":3}',
                      '{"gain":+2}', '{"gain":.5}', '{"gain":NaN}', '{"gain":Infinity}'):
            with self.subTest(patch=patch):
                self.setting("check", "-SetJson", patch, ok=False)

    def test_numeric_spelling_and_name_do_not_change_physics_hash(self):
        baseline = self.setting("show")
        changed = self.setting("check", "-SetJson", '{"gain":2e1,"shaping_tau_us":0.500}')
        renamed = copy.deepcopy(self.original); renamed["name"] = "another-name"
        other = self.setting("show", "-SettingsFile", self.put("inputs/renamed.json", renamed))
        self.assertEqual(baseline["physics_sha256"], changed["physics_sha256"])
        self.assertEqual(baseline["physics_sha256"], other["physics_sha256"])

    def test_readonly_modes_no_writes_and_reuse_labels(self):
        self.put("inputs/other.json", self.original)
        before = snapshot(self.root)
        for mode in ("show", "check", "compare"):
            extra = ("-CompareTo", "inputs/other.json") if mode == "compare" else ()
            result = self.setting(mode, *extra)
            self.assertEqual(snapshot(self.root), before)
            self.assertFalse((self.root / ".local").exists())
            self.assertIn("NOT_CHECKED", result["reuse"]["artifact_verified_supported_reuse"])
            self.assertIn("NOT_IMPLEMENTED", result["reuse"]["electronics_only_replay"])
            self.assertIn("full charge waveforms", result["reuse"]["dependency_based_theoretical_reuse"])
        self.assertTrue(result["comparison"]["same_physics"])

    def test_cmd_wrapper_readonly(self):
        before = snapshot(self.root)
        for mode, extra, expected_code in (("show", ["-Json"], 0),
                                          ("check", ["-SettingsFile", "../bad.json"], 2)):
            command = ["cmd.exe", "/c", "Run.cmd", "settings", mode, *extra]
            done = subprocess.run(command, cwd=self.root, capture_output=True, text=True, timeout=25)
            (self.home / f"wrapper-{mode}.json").write_text(json.dumps({
                "command": command, "exit_code": done.returncode, "stdout": done.stdout,
                "stderr": done.stderr}, indent=2), encoding="utf-8")
            self.assertEqual(done.returncode, expected_code, done.stdout + done.stderr)
            if mode == "show":
                self.assertEqual(json.loads(done.stdout)["profile"], self.original)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".local").exists())

    def test_compare_reports_exact_changes_without_execution(self):
        other = copy.deepcopy(self.original); other["settings"]["threshold_V"] = 0.002
        self.put("inputs/other.json", other)
        result = self.setting("compare", "-CompareTo", "inputs/other.json")
        self.assertFalse(result["comparison"]["same_physics"])
        self.assertEqual(result["comparison"]["changes"], {"threshold_V": {"from": 0.001, "to": 0.002, "unit": "V"}})
        self.assertFalse((self.root / ".local").exists())

    def test_unsafe_paths_and_save_names(self):
        for path in ("../escape.json", "C:/elsewhere.json", "simulation/../readout.json",
                     "simulation/native_readout_profile.json:stream", "simulation/*.json",
                     "simulation/CON.json", "simulation./x", "//server/file"):
            self.setting("check", "-SettingsFile", path, ok=False)
        for name in ("../escape", "NUL", "a/b", "bad.name", "CON", "bad name", "a" * 65):
            self.setting("save", "-SaveName", name, ok=False)
        self.assertFalse((self.root / ".local").exists())

    def test_junction_paths_rejected_hardlinks_readonly(self):
        target = self.root / "inputs"; target.mkdir()
        shutil.copy2(self.root / "simulation/native_readout_profile.json", target / "profile.json")
        link = self.root / "linked"
        command = ["cmd.exe", "/c", "mklink", "/J", str(link), str(target)]
        made = subprocess.run(command, capture_output=True, text=True)
        (self.home / "junction.json").write_text(json.dumps({"command": command, "exit_code": made.returncode,
                                                            "stdout": made.stdout, "stderr": made.stderr}))
        self.assertEqual(made.returncode, 0, made.stderr)
        self.setting("show", "-SettingsFile", "linked/profile.json", ok=False)
        (self.root / ".local").mkdir()
        command = ["cmd.exe", "/c", "mklink", "/J", str(self.root / ".local/electronics-profiles"), str(target)]
        made = subprocess.run(command, capture_output=True, text=True)
        (self.home / "save-junction.json").write_text(json.dumps({"command": command, "exit_code": made.returncode,
                                                                 "stdout": made.stdout, "stderr": made.stderr}))
        self.assertEqual(made.returncode, 0, made.stderr)
        self.setting("save", "-SaveName", "unsafe", ok=False)
        self.assertFalse((target / "unsafe.json").exists())
        (self.root / "hard.json").hardlink_to(target / "profile.json")
        before = (target / "profile.json").read_bytes()
        self.setting("check", "-SettingsFile", "hard.json")
        self.assertEqual((target / "profile.json").read_bytes(), before)

    def test_input_profile_mutation_rejected(self):
        self.put("inputs/custom.json", self.original)
        saved = self.setting("save", "-SaveName", "bound", "-SettingsFile", "inputs/custom.json")
        changed = copy.deepcopy(self.original); changed["settings"]["gain"] = 21
        self.put("inputs/custom.json", changed)
        self.setting("check", "-SettingsFile", saved["saved_path"], ok=False)

    def test_source_mutation_and_pinned_default_mutation(self):
        saved = self.setting("save", "-SaveName", "bound")
        source = self.root / "simulation/readout_profiles.jl"
        source.write_bytes(source.read_bytes() + b"\n# changed\n")
        self.setting("check", "-SettingsFile", saved["saved_path"], ok=False)
        data = copy.deepcopy(self.original); data["settings"]["gain"] = 21
        self.put("simulation/native_readout_profile.json", data)
        self.setting("check", ok=False)

    def test_rehashed_resolved_config_mutation_rejected(self):
        saved = self.setting("save", "-SaveName", "bound")
        path = self.root / saved["saved_path"]
        data = json.loads(path.read_text()); data["configuration"]["gain"] = 21
        # Use exactly the production canonical serializer/hash, then prove the
        # independent profile->configuration comparison still catches this edit.
        self.put(saved["saved_path"], data)
        expr = (f". {psquote(self.root / 'tools/electronics_settings.ps1')}; "
                f"$b=Get-Content -LiteralPath {psquote(path)} -Raw|ConvertFrom-Json; "
                "$b.physics_sha256=Get-ESPhysicsHash $b.configuration; "
                f"[IO.File]::WriteAllText({psquote(path)},($b|ConvertTo-Json -Depth 16))")
        command = ["powershell.exe", "-NoProfile", "-Command", expr]
        done = subprocess.run(command, capture_output=True, text=True)
        (self.home / "rehash.json").write_text(json.dumps({"command": command, "exit_code": done.returncode,
                                                         "stdout": done.stdout, "stderr": done.stderr}))
        self.assertEqual(done.returncode, 0, done.stderr)
        result = self.setting("check", "-SettingsFile", saved["saved_path"], ok=False)
        self.assertIn("Independent resolved configuration", " ".join(result.stderr.split()))

    def test_bundle_exact_keys_and_types(self):
        saved = self.setting("save", "-SaveName", "bound")
        original = json.loads((self.root / saved["saved_path"]).read_text())
        mutations = []
        bad = copy.deepcopy(original); bad["extra"] = 1; mutations.append(bad)
        bad = copy.deepcopy(original); del bad["configuration"]; mutations.append(bad)
        for value in (True, 1.0, 2):
            bad = copy.deepcopy(original); bad["revision"] = value; mutations.append(bad)
        for field in ("schema_version", "adc_bits", "max_samples_per_event", "trace_max_points"):
            bad = copy.deepcopy(original); bad["configuration"][field] = float(bad["configuration"][field]); mutations.append(bad)
        bad = copy.deepcopy(original); bad["configuration"]["require_all_events"] = 1; mutations.append(bad)
        bad = copy.deepcopy(original); bad["provenance"]["input"]["schema_version"] = 2.0; mutations.append(bad)
        bad = copy.deepcopy(original); bad["provenance"]["input"]["path"] = 2; mutations.append(bad)
        for index, bad in enumerate(mutations):
            self.put(f"inputs/mutated{index}.json", bad)
            self.setting("check", "-SettingsFile", f"inputs/mutated{index}.json", ok=False)

    def test_resume_and_custom_execution_fail_before_runtime_or_writes(self):
        before = snapshot(self.root)
        for action in ("run", "resume"):
            self.invoke(action, "-ElectronicsProfile", "missing.json", "-DryRun", ok=False)
        for flag, value in (("-Preset", "smoke"), ("-Detector", "AK02"), ("-Seed", "2"),
                            ("-Pilot", ".local/pilot"), ("-Scenario", "lbnl-cs137")):
            result = self.invoke("resume", "-Name", "none", "-DryRun", flag, value, ok=False)
            self.assertIn("override forbidden", result.stderr)
            result = self.invoke("menu", flag, value, ok=False)
            self.assertIn("override forbidden", result.stderr)
        result = self.invoke("-Output", ".local/never", "-ElectronicsProfile", "missing.json",
                             script="tools/run_native_campaign.ps1", ok=False)
        self.assertIn("ElectronicsProfile", result.stderr)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / ".local").exists())

    def test_mode_mixing_is_rejected(self):
        for arguments in (("show", "-SetJson", '{"gain":10}'), ("check", "-SaveName", "bad"),
                          ("show", "-CompareTo", "simulation/native_readout_profile.json"),
                          ("compare",), ("show", "-BuildExporter"), ("show", "-DryRun")):
            self.setting(*arguments, ok=False)
        self.invoke("run", "-SetJson", '{"gain":10}', ok=False)
        self.assertFalse((self.root / ".local").exists())

    def test_interactive_simple_and_advanced(self):
        # Piped answers use the same Read-Host path as the Windows console.
        self.invoke("settings", stdin="simple\n0.8\n\n\n\n\ninteractive\n")
        saved = self.setting("check", "-SettingsFile", ".local/electronics-profiles/interactive.json")
        expected = copy.deepcopy(self.original); expected["settings"]["shaping_tau_us"] = 0.8
        self.assertEqual(saved["configuration"], self.expected(expected))
        answers = 'advanced\n\n\n\n\n\n0.7\n40\n35\n"legacy_reject_negative_input"\n0\n90000\nadvanced\n'
        self.invoke("settings", stdin=answers)
        saved = self.setting("check", "-SettingsFile", ".local/electronics-profiles/advanced.json")
        self.assertEqual(saved["configuration"]["feedback_capacitance_pF"], 0.7)
        self.assertEqual(saved["configuration"]["peak_gate_end_ns"], 90000)

    def test_original_backend_inventory_and_default_argument_regression(self):
        # Source-only regression: optional custom execution did not rewrite the
        # pinned driver, independent validation, or original numerical inputs.
        # Exact dbc3590 baselines; no Git history needed in a source archive.
        baseline_sha256 = {
            "tools/run_native_campaign.ps1": "0736d2718c94897b17cef928d66d71ca1f91058b92c09a7865fae27b3d27770c",
            "tools/native_run_validation.ps1": "b19083dcbedce91620decd101b20fb85c81e285e8b0b70fecd7053dfaca1bb9d",
            "simulation/native_readout_profile.json": "7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6",
            "simulation/readout_demo.json": "33eb64724736c78852795ea001889759152ffefc22de9c4db6815fd1aaf8ee9e"
        }
        for rel, expected in baseline_sha256.items():
            self.assertEqual(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest(), expected, rel)


    def test_unknown_cli_options_and_extra_arguments_rejected(self):
        before = snapshot(self.root)
        for action in ('settings', 'run', 'resume'):
            for option in ('-SettingsFiles', '-Profile', '-UnrecognizedSetting'):
                args = [action] + (['check'] if action == 'settings' else [])
                result = self.invoke(*args, option, 'missing.json', ok=False)
                self.assertIn('parameter', result.stderr.lower())
        self.invoke('settings', 'check', '-Json', 'unexpected-positional', ok=False)
        self.assertEqual(snapshot(self.root), before)
        self.assertFalse((self.root / '.local').exists())

    def test_derived_save_checks_changed_and_missing_ancestor(self):
        original_path = self.put('inputs/original.json', self.original)
        first = self.setting('save', '-SettingsFile', original_path, '-SaveName', 'first')
        second = self.setting('save', '-SettingsFile', first['saved_path'], '-SaveName', 'second')
        third = self.setting('save', '-SettingsFile', second['saved_path'], '-SaveName', 'third')
        self.setting('check', '-SettingsFile', third['saved_path'])
        changed = copy.deepcopy(self.original); changed['settings']['gain'] = 21
        self.put(original_path, changed)
        before = snapshot(self.root)
        result = self.setting('check', '-SettingsFile', third['saved_path'], ok=False)
        self.assertIn('Input profile binding', ' '.join(result.stderr.split()))
        self.assertEqual(snapshot(self.root), before)
        (self.root / original_path).unlink()
        before = snapshot(self.root)
        result = self.setting('check', '-SettingsFile', third['saved_path'], ok=False)
        self.assertIn('Settings input missing', ' '.join(result.stderr.split()))
        self.assertEqual(snapshot(self.root), before)
    def test_provenance_cycle_and_depth_limit(self):
        current = 'simulation/native_readout_profile.json'
        for index in range(15):
            saved = self.setting('save', '-SettingsFile', current, '-SaveName', f'depth{index}')
            current = saved['saved_path']
        self.setting('check', '-SettingsFile', current)
        before = snapshot(self.root)
        result = self.setting('save', '-SettingsFile', current, '-SaveName', 'too-deep', ok=False)
        self.assertIn('exceed 16 provenance', ' '.join(result.stderr.split()))
        self.assertEqual(snapshot(self.root), before)
        cyclic = self.setting('save', '-SaveName', 'cyclic')
        path = cyclic['saved_path']; bundle = json.loads((self.root / path).read_text())
        bundle['provenance']['input'] = dict(path=path, sha256='0' * 64, schema_version=1, kind='electronics_settings_bundle_v1')
        self.put(path, bundle)
        before = snapshot(self.root)
        result = self.setting('check', '-SettingsFile', path, ok=False)
        self.assertIn('Cyclic settings provenance', ' '.join(result.stderr.split()))
        self.assertEqual(snapshot(self.root), before)



if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--evidence", required=True)
    options = parser.parse_args()
    EVIDENCE = (ROOT / options.evidence).resolve()
    if not EVIDENCE.is_relative_to(ROOT / ".local/electronics-settings-v1"):
        parser.error("Evidence must be below .local/electronics-settings-v1")
    EVIDENCE.mkdir(parents=True, exist_ok=False)
    shutil.copy2(__file__, EVIDENCE / "executed_test.py")
    unittest.main(argv=[__file__], verbosity=2)
