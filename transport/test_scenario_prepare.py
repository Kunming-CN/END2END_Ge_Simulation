"""Finite M11a pure/mocked checks; all retained fixtures are below .local/m11a-preparation."""
import builtins
import copy
import importlib.util
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

import scenario_prepare as s

POINTS = {
    "AK02": list(zip([0, 7.8, 7.8, 12.65, 12.65, 7.75, 7.75, 2.95, 2.95, 0, 0],
                     [2.1, 2.1, 0, 0, 9.4, 9.4, 7.9, 7.9, 9.4, 9.4, 2.1])),
    "SAP22": list(zip([0, 8.85, 8.85, 12.75, 12.75, 8.75, 8.75, 3.85, 3.85, 0, 0],
                      [4.2, 4.2, 0, 0, 10, 10, 7, 7, 10, 10, 4.2])),
}


def model_fixture(model):
    # Native unit tests mock YAML parsing only; check itself uses exact pinned bytes.
    return {"detectors": [{"semiconductor": {"temperature": 78}, "contacts": [
        {"id": 1, "potential": 0}, {"id": 2, "potential": 500 if model == "AK02" else 700}]}]}, POINTS[model]


def report_fixture(plan):
    s.native_helpers()
    volumes = []
    for name, original_path, copy_number, material in s.LEDGER:
        density, fractions = s.MATERIALS[material]
        volumes.append({"name": name, "original_path": original_path, "copy_number": copy_number,
            "material": material, "density_g_cm3": density,
            "elements": [{"name": n, "mass_fraction": f} for n, f in fractions.items()],
            "translation_global_mm": [0, 0, 0], "rotation_local_to_global": s.h.TRANSFORM["rotation_local_to_global"], "overlap": False})
    volumes[5]["translation_global_mm"] = [0, 1.473, -3.710]
    volumes[16].update(translation_global_mm=plan["coordinate_transform"]["translation_global_mm"], rotation_local_to_global=s.ROTATION)
    for v in volumes[18:20]:
        v.update(translation_global_mm=plan["source_position_global_mm"], rotation_local_to_global=s.ROTATION)
    probes = s.h.probe_points(POINTS[plan["assets"]["detector"]["id"]])
    return {"schema_version": 1, "geant4_version_number": 1132, "overlap_seed": 26092632,
        "overlap_samples": 10000, "source_inside_fill": True, "overlaps_passed": True,
        "crystal_volume_mm3": s.h.reference_volume(plan["assets"]["detector"]["id"]), "volumes": volumes,
        "probes": [{"index": i, "classification": p["expected"]} for i, p in enumerate(probes)]}


class PreparationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        base = s.ROOT / ".local/m11a-preparation/mock-tests"
        base.mkdir(parents=True, exist_ok=True)
        for index in range(1, 10000):
            candidate = base / ("run-" + str(index))
            try:
                candidate.mkdir()
                cls.bundle = candidate
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("finite fixture reservation exhausted")
        cls.start = time.perf_counter()
        cls.case_number = 0

    @classmethod
    def tearDownClass(cls):
        (cls.bundle / "fixture-receipt.json").write_text(s.json_text({
            "kind": "mocked_preparation_tests", "wall_s": time.perf_counter() - cls.start,
            "case_count": cls.case_number, "native_exporter_calls": 0,
            "radiation_charge_readout_calls": 0, "fixtures_retained": True}), encoding="utf-8")

    def setUp(self):
        type(self).case_number += 1
        self.case = self.bundle / ("case-" + str(type(self).case_number))
        self.case.mkdir()
        self.asset_dir = self.case / "assets"
        self.asset_dir.mkdir()
        for aid, record in s.asset_records().items():
            (self.asset_dir / (aid + ".json")).write_text(s.json_text(record), encoding="utf-8")
        self.refs = patch.object(s, "asset_ref", side_effect=lambda aid: (self.asset_dir / (aid + ".json")).relative_to(s.ROOT).as_posix())
        self.refs.start()
        self.addCleanup(self.refs.stop)
        self.exporter = s.ROOT / ".local/m2a/cs137-build-v1/cryostat_export"

    def config(self, model="AK02", source="cs137_point_decay_v1", pose="nominal", name="instance.json"):
        roles = {"cryostat": "lbnl_modular_nominal_v1", "detector": model, "source": source}
        cfg = {"schema_version": 1, "kind": "source_instance_v1", "units": s.UNITS,
               "source_pose": pose, "primary_count": 20, "seed": 26092631}
        for role, aid in roles.items():
            cfg[role] = {"id": aid, "version": 1, "ref": s.asset_ref(aid), "sha256": s.sha256(s.ROOT / s.asset_ref(aid))}
        p = self.case / name
        p.write_text(s.json_text(cfg), encoding="utf-8")
        return p

    def write_config(self, p, cfg):
        p.write_text(s.json_text(cfg), encoding="utf-8")

    def test_check_imports_only_standard_library_and_creates_nothing(self):
        # A fresh import remains functional when every numerical/native helper import refuses.
        real_import = builtins.__import__
        def limited_import(name, *args, **kwargs):
            if name.split(".")[0] in {"numpy", "yaml", "handoff", "cs137"}:
                raise AssertionError("check imported a native/numerical helper")
            return real_import(name, *args, **kwargs)
        spec = importlib.util.spec_from_file_location("pure_m11a_adapter", s.HERE / "scenario_prepare.py")
        module = importlib.util.module_from_spec(spec)
        real_open = Path.open
        def read_only(path, mode="r", *args, **kwargs):
            if any(flag in mode for flag in "wax+"):
                raise AssertionError("check attempted output")
            return real_open(path, mode, *args, **kwargs)
        with patch("builtins.__import__", side_effect=limited_import), patch.object(s.subprocess, "run", side_effect=AssertionError("subprocess")), patch.object(Path, "open", read_only), patch.object(Path, "mkdir", side_effect=AssertionError("mkdir")):
            spec.loader.exec_module(module)
            before = {p.relative_to(self.case) for p in self.case.rglob("*")}
            result = module.check(s.ROOT / "scenarios/m11a-ak02-cs137_point_decay_v1-nominal.json")
            after = {p.relative_to(self.case) for p in self.case.rglob("*")}
        self.assertEqual(before, after)
        self.assertNotIn("h", module.__dict__)
        self.assertEqual(result["supported_stages"], ["check", "prepare"])
        self.assertNotIn("contour_rz_mm", result)

    def test_every_model_source_pose_and_fixed_model_binding(self):
        with patch.object(s.subprocess, "run", side_effect=AssertionError("subprocess")):
            for model in ("AK02", "SAP22"):
                for source in ("cs137_point_decay_v1", "mono_gamma_662_axis_v1"):
                    for pose in s.POSES:
                        plan = s.check(self.config(model, source, pose, model + source + pose + ".json"))
                        self.assertEqual(plan["source_position_global_mm"], s.POSES[pose])
                        self.assertEqual(plan["assets"]["detector"]["temperature_K"], 78)
                        self.assertEqual(plan["assets"]["detector"]["contacts"], [{"id": 1, "potential_V": 0}, {"id": 2, "potential_V": 500 if model == "AK02" else 700}])
                        self.assertEqual(plan["stages"]["transport"], "not_executed")

    def test_hash_and_public_check_without_file_digest(self):
        p = self.config()
        blob = self.case / "multiple-chunks.bin"
        payload = b"bounded hash fixture\x00" * 110000
        blob.write_bytes(payload)
        expected = s.hashlib.sha256(payload).hexdigest()
        # Python 3.10 lacks file_digest. Remove it temporarily rather than
        # claiming a fresh-machine or actual Python 3.10 acceptance run.
        with patch.dict(s.hashlib.__dict__), patch.object(s.subprocess, "run", side_effect=AssertionError("subprocess")):
            s.hashlib.__dict__.pop("file_digest", None)
            self.assertFalse(hasattr(s.hashlib, "file_digest"))
            self.assertEqual(s.sha256(blob), expected)
            plan = s.check(p)
        self.assertEqual(plan["assets"]["detector"]["id"], "AK02")

    def test_invalid_instance_fields_refuse_before_outputs_or_subprocess(self):
        mutations = [("primary_count", True), ("primary_count", 21), ("seed", False), ("seed", 0),
                     ("source_pose", "arbitrary"), ("schema_version", True), ("kind", "run"),
                     ("units", {**s.UNITS, "length": "m"}), ("extra", "command")]
        with patch.object(s.subprocess, "run", side_effect=AssertionError("subprocess")):
            for index, (key, value) in enumerate(mutations):
                p = self.config(name="invalid-" + str(index) + ".json")
                cfg = s.strict_load(p); cfg[key] = value; self.write_config(p, cfg)
                out = self.case / ("output-" + str(index))
                with self.assertRaises(ValueError):
                    s.prepare(p, out, self.exporter)
                self.assertFalse(out.exists())

    def test_unsafe_unknown_extra_asset_refs_versions_hashes(self):
        for index, (key, value) in enumerate([("id", "Am241"), ("version", True), ("version", 2),
                ("ref", "../models/AK02.yaml"), ("ref", "C:/private.json"), ("sha256", "0" * 64), ("command", "bad")]):
            p = self.config(name="ref-" + str(index) + ".json")
            cfg = s.strict_load(p); cfg["source"][key] = value; self.write_config(p, cfg)
            with self.assertRaises(ValueError):
                s.check(p)

    def test_duplicate_and_nonfinite_json_refuse(self):
        for index, text in enumerate(['{"schema_version":1,"schema_version":1}', '{"seed":NaN}', '{"seed":Infinity}', '{"seed":1e999}']):
            p = self.case / ("parse-" + str(index) + ".json"); p.write_text(text, encoding="utf-8")
            with self.assertRaises(ValueError):
                s.check(p)

    def test_rehashed_semantic_asset_edits_refuse(self):
        edits = [("source", "angular_policy", "isotropic"), ("source", "clock_policy", "activity"),
                 ("source", "direction_global", [0, 1, 0]), ("source", "kinetic_energy_keV", True),
                 ("source", "extra", "unsupported"), ("detector", "temperature_K", 77),
                 ("detector", "readout_contact_id", 2), ("detector", "contacts", [{"id": 1, "potential_V": 0}, {"id": 2, "potential_V": 500}]),
                 ("cryostat", "fill_material", "G4_AIR"), ("cryostat", "capsule_axis_global", [0, 0, 1]),
                 ("cryostat", "supported_stages", ["check", "prepare", "run"])]
        for index, (role, key, value) in enumerate(edits):
            p = self.config("SAP22", "mono_gamma_662_axis_v1", name="semantic-" + str(index) + ".json")
            cfg = s.strict_load(p); ap = s.ROOT / cfg[role]["ref"]
            original = s.strict_load(ap); changed = copy.deepcopy(original); changed[key] = value
            ap.write_text(s.json_text(changed), encoding="utf-8")
            cfg[role]["sha256"] = s.sha256(ap); self.write_config(p, cfg)
            with self.assertRaisesRegex(ValueError, "semantics"):
                s.check(p)
            ap.write_text(s.json_text(original), encoding="utf-8")

    def mock_prepare(self, p, output, mutate=None, returncode=0, log="native fixture success\n"):
        s.native_helpers()
        plan = s.check(p)
        report = report_fixture(plan)
        upstream = {item["name"]: item["sha256"] for item in s.strict_load(s.ROOT / "transport/cryostat-source.json")["files"]}
        calls = []
        def fake_run(command, **kwargs):
            calls.append((command, kwargs))
            self.assertEqual(len(command), 7)
            self.assertFalse(kwargs["shell"])
            self.assertEqual(command[0], str(self.exporter))
            self.assertNotIn("remage", command); self.assertNotIn("julia", command)
            (output / "geometry.gdml").write_text("<gdml mocked='true'/>\n", encoding="utf-8")
            if mutate:
                mutate(report)
            (output / "geometry-report.json").write_text(s.json_text(report), encoding="utf-8")
            kwargs["stdout"].write(log)
            return types.SimpleNamespace(returncode=returncode)
        with patch.object(s.h, "load_model", side_effect=model_fixture), patch.object(s.c, "upstream_hashes", return_value=upstream), patch.object(s.subprocess, "run", side_effect=fake_run):
            meta = s.prepare(p, output, self.exporter)
        self.assertEqual(len(calls), 1)
        return meta, calls

    def test_mock_prepare_both_models_sources_poses_and_hashes(self):
        for model in ("AK02", "SAP22"):
            for source in ("cs137_point_decay_v1", "mono_gamma_662_axis_v1"):
                for pose in s.POSES:
                    name = model + source + pose
                    p = self.config(model, source, pose, name + ".json")
                    meta, calls = self.mock_prepare(p, self.case / name)
                    self.assertEqual(meta["kind"], "scenario_source_prepared_v1")
                    self.assertEqual(meta["stages"]["transport"], "transport_not_executed")
                    self.assertNotIn("events", meta)
                    params = [float(x) for x in (self.case / name / "parameters.txt").read_text().split()]
                    self.assertEqual(len(params), 18); self.assertEqual(params[11:14], s.POSES[pose])
                    self.assertEqual(params[-1], 10000)
                    for filename, digest in meta["files_sha256"].items():
                        self.assertEqual(s.sha256(self.case / name / filename), digest)
                    self.assertEqual(s.strict_load(self.case / name / "prepare-receipt.json")["status"], "complete")

    def test_native_exit_zero_bad_reports_refuse_and_retain_failure(self):
        mutations = [lambda r: r.update(schema_version=True), lambda r: r.update(geant4_version_number=1131),
            lambda r: r.update(overlap_seed=26092631), lambda r: r.update(overlap_samples=9999),
            lambda r: r.update(source_inside_fill=1), lambda r: r.update(overlaps_passed=False),
            lambda r: r.update(crystal_volume_mm3=r["crystal_volume_mm3"] + 1),
            lambda r: r["probes"].pop(), lambda r: r["probes"][0].update(index=True),
            lambda r: r["probes"][0].update(classification="outside"),
            lambda r: r["volumes"].pop(), lambda r: r["volumes"][8].update(copy_number=-33),
            lambda r: r["volumes"][16].update(name="ledger_16"), lambda r: r["volumes"][16].update(material="G4_AIR"),
            lambda r: r["volumes"][19].update(original_path="/RmP124/nominal_source_fill"),
            lambda r: r["volumes"][18].update(material="G4_POLYETHYLENE"),
            lambda r: r["volumes"][1].update(overlap=0), lambda r: r["volumes"][1].update(overlap=True),
            lambda r: r["volumes"][1].update(density_g_cm3=True),
            lambda r: r["volumes"][1]["elements"][0].update(mass_fraction=0.9),
            lambda r: r["volumes"][16].update(translation_global_mm=[0, 0.00145, 0.00029]),
            lambda r: r["volumes"][18].update(translation_global_mm=[0, 42.073, 0.290]),
            lambda r: r["volumes"][19].update(rotation_local_to_global=[[1,0,0],[0,1,0],[0,0,1]]),
            lambda r: r["volumes"][1].update(translation_global_mm=[True,0,0]),
            lambda r: r["volumes"][1].update(rotation_local_to_global=[[1,0,0],[0,1,0],[0,0,-1]]),
            lambda r: r.update(extra="unsupported")]
        for index, mutate in enumerate(mutations):
            p = self.config(name="bad-native-" + str(index) + ".json")
            out = self.case / ("bad-native-" + str(index))
            with self.assertRaises(ValueError):
                self.mock_prepare(p, out, mutate)
            self.assertFalse((out / "prepared.json").exists())
            self.assertTrue((out / "geometry-report.json").is_file())
            self.assertEqual(s.strict_load(out / "prepare-receipt.json")["status"], "failed")

    def test_nonzero_and_error_log_refuse(self):
        for index, (code, log) in enumerate([(1,"ordinary failure\n"), (0,"*** Fatal\n"), (0,"Overlap is detected\n"), (0,"cryostat_export: failed\n")]):
            out = self.case / ("exit-" + str(index))
            with self.assertRaises(ValueError):
                self.mock_prepare(self.config(name="exit-" + str(index) + ".json"), out, returncode=code, log=log)
            self.assertFalse((out / "prepared.json").exists())

    def test_macro_common_settings_and_exact_source_suffixes(self):
        for source in ("cs137_point_decay_v1", "mono_gamma_662_axis_v1"):
            plan = s.check(self.config(source=source, name=source + ".json"))
            report = report_fixture(plan)
            macro = s.source_macro(report, plan)
            original = s.c.macro_text(report, 20, plan["source_position_global_mm"])
            for line in original.splitlines():
                if line.startswith(("/gps/", "/run/beamOn", "/RMG/Generator/")) or line in s.DECAY_ONLY:
                    continue
                self.assertEqual(macro.splitlines().count(line), 1)
            self.assertEqual(macro.count("/RMG/Generator/Select GPS"), 1)
            self.assertEqual(macro.count("/run/beamOn 20"), 1)
            if source == "cs137_point_decay_v1":
                self.assertEqual(macro, original)
            else:
                self.assertEqual(macro.splitlines()[-10:], ["/RMG/Generator/Select GPS", "/gps/particle gamma", "/gps/pos/type Point",
                    "/gps/pos/centre 0 37.073 0.28999999999999998 mm", "/gps/direction 0 -1 0", "/gps/ene/type Mono",
                    "/gps/ene/mono 662 keV", "/gps/time 0 ns", "/gps/number 1", "/run/beamOn 20"])
                self.assertNotIn("/gps/ion", macro)
                self.assertTrue(all(line not in macro.splitlines() for line in s.DECAY_ONLY))
                self.assertIn("/RMG/Output/Track/StoreAlways true", macro)
                self.assertIn("/RMG/Output/Germanium/DiscardZeroEnergyHits false", macro)

    def test_unexpected_macro_helper_shape_refuses(self):
        plan = s.check(self.config(source="mono_gamma_662_axis_v1")); report = report_fixture(plan)
        original = s.c.macro_text(report, 20, plan["source_position_global_mm"])
        for changed in (original + "/gps/number 2\n", original.replace("/gps/ion 55 137", "/gps/ion 95 241"), original.replace("/run/initialize", "/RMG/Generator/Select GPS\n/run/initialize")):
            with patch.object(s.c, "macro_text", return_value=changed), self.assertRaises(ValueError):
                s.source_macro(report, plan)

    def test_nonfinite_report_fields_and_fill_boundary_refuse(self):
        plan = s.check(self.config()); report = report_fixture(plan)
        probes = s.h.probe_points(POINTS["AK02"])
        for section, key in ((report,"crystal_volume_mm3"), (report["volumes"][1],"density_g_cm3"), (report["volumes"][1]["elements"][0],"mass_fraction")):
            original = section[key]
            for value in (float("nan"), float("inf"), True):
                section[key] = value
                with self.assertRaises(ValueError):
                    s.validate_report(report, plan, probes)
            section[key] = original
        # A mismatched mm->m emission point cannot be accepted against the report pose.
        shifted_plan = copy.deepcopy(plan)
        shifted_plan["source_position_global_mm"] = [0, 0.037073, 0.000290]
        with self.assertRaisesRegex(ValueError, "translation"):
            s.validate_report(report, shifted_plan, probes)
        fill = report["volumes"][19]
        s.require_source_inside_fill_mm([2.899, 37.472, 0.290], fill)
        for point in ([2.9,37.073,0.290], [0,37.473,0.290], [3,37.073,0.290], [0,0.037073,0.000290]):
            with self.assertRaisesRegex(ValueError, "strictly inside"):
                s.require_source_inside_fill_mm(point, fill)

    def test_frozen_config_and_generated_inputs_refuse(self):
        for mode in ("config", "generated"):
            p = self.config(name=mode + ".json"); out = self.case / mode
            def mutate(report):
                if mode == "config":
                    p.write_text(p.read_text() + " ", encoding="utf-8")
                else:
                    (out / "canonical.gdml").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "changed"):
                self.mock_prepare(p, out, mutate)
            self.assertFalse((out / "prepared.json").exists())
            self.assertEqual(s.strict_load(out / "prepare-receipt.json")["status"], "failed")

    def binding_fixture(self, role, name):
        p = self.config(name=name + ".json")
        original_project_file = s.project_file
        nominal = self.case / (name + "-nominal.json")
        nominal.write_bytes((s.ROOT / "transport/cryostat_nominal.json").read_bytes())
        def resolve(path):
            if Path(path) == s.ROOT / "transport/cryostat_nominal.json":
                return original_project_file(nominal)
            return original_project_file(path)
        if role == "config":
            target = p
            changed = s.strict_load(p)
            aid = "mono_gamma_662_axis_v1"
            changed["source"] = {"id": aid, "version": 1, "ref": s.asset_ref(aid),
                                 "sha256": s.sha256(s.ROOT / s.asset_ref(aid))}
            changed["source_pose"] = "plus5mm"
            replacement = s.json_text(changed).encode("utf-8")
        elif role == "asset":
            target = s.ROOT / s.strict_load(p)["source"]["ref"]
            replacement = target.read_bytes() + b" "
        else:
            target = nominal
            changed = s.strict_load(nominal)
            changed["coordinate_transform"]["translation_global_mm"][1] += 1
            replacement = s.json_text(changed).encode("utf-8")
        key = "transport/cryostat_nominal.json" if role == "nominal" else target.relative_to(s.ROOT).as_posix()
        return p, target, replacement, key, resolve

    def assert_binding_refusal(self, p, out):
        s.native_helpers()
        upstream = {item["name"]: item["sha256"] for item in s.strict_load(s.ROOT / "transport/cryostat-source.json")["files"]}
        with patch.object(s.h, "load_model", side_effect=model_fixture), patch.object(s.c, "upstream_hashes", return_value=upstream), patch.object(s.subprocess, "run") as dispatch:
            with self.assertRaisesRegex(ValueError, "checked plan input changed"):
                s.prepare(p, out, self.exporter)
            dispatch.assert_not_called()
        self.assertFalse(out.exists())

    def test_postcheck_config_asset_nominal_changes_refuse_before_output(self):
        original_check = s.check
        for role in ("config", "asset", "nominal"):
            name = "postcheck-" + role
            p, target, replacement, key, resolve = self.binding_fixture(role, name)
            witness = s.sha256(target)
            plans = []
            def change_after_check(path):
                plan = original_check(path)
                plans.append(plan)
                target.write_bytes(replacement)
                return plan
            with patch.object(s, "project_file", side_effect=resolve), patch.object(s, "check", side_effect=change_after_check):
                self.assert_binding_refusal(p, self.case / name)
            self.assertEqual(len(plans), 1)  # No silent re-resolution/rebase.
            self.assertEqual(plans[0]["input_sha256"][key], witness)
            self.assertNotEqual(s.sha256(target), witness)
            self.assertEqual(plans[0]["instance"]["source"]["id"], "cs137_point_decay_v1")
            self.assertEqual(plans[0]["instance"]["source_pose"], "nominal")

    def test_config_asset_nominal_parse_hash_same_snapshot_before_output(self):
        original_check, original_loads = s.check, s.json.loads
        for role in ("config", "asset", "nominal"):
            name = "snapshot-" + role
            p, target, replacement, key, resolve = self.binding_fixture(role, name)
            before = target.read_bytes()
            witness = s.hashlib.sha256(before).hexdigest()
            parsed_before = original_loads(before.decode("utf-8"))
            plans, mutations = [], []
            def change_after_read(text, *args, **kwargs):
                if text == before.decode("utf-8") and not mutations:
                    target.write_bytes(replacement)
                    mutations.append(role)
                return original_loads(text, *args, **kwargs)
            def record_check(path):
                plan = original_check(path)
                plans.append(plan)
                return plan
            with patch.object(s, "project_file", side_effect=resolve), patch.object(s.json, "loads", side_effect=change_after_read), patch.object(s, "check", side_effect=record_check):
                self.assert_binding_refusal(p, self.case / name)
            self.assertEqual(mutations, [role])
            self.assertEqual(len(plans), 1)
            self.assertEqual(plans[0]["input_sha256"][key], witness)
            self.assertNotEqual(s.sha256(target), witness)
            if role == "config":
                self.assertEqual(plans[0]["instance"], parsed_before)
            elif role == "asset":
                self.assertEqual(plans[0]["assets"]["source"], parsed_before)
            else:
                self.assertEqual(plans[0]["nominal_geometry"], parsed_before)
                self.assertEqual(plans[0]["coordinate_transform"], parsed_before["coordinate_transform"])

    def test_output_no_clobber_and_wrong_exporter_before_subprocess(self):
        s.native_helpers()
        p = self.config(); existing = self.case / "existing"; existing.mkdir(); marker = existing / "science.txt"; marker.write_text("preserve")
        wrong = self.case / "wrong-exporter"; wrong.write_text("wrong")
        with patch.object(s.h, "load_model", side_effect=model_fixture), patch.object(s.subprocess, "run", side_effect=AssertionError("subprocess")):
            for output, exporter in ((existing,self.exporter), (self.case / "missing",self.case / "absent"), (self.case / "wrong",wrong), (s.ROOT / "scenarios/unsafe",self.exporter)):
                with self.assertRaises(ValueError):
                    s.prepare(p, output, exporter)
            with self.assertRaises(ValueError):
                s.h.publish_json(marker, {"bad": True})
        self.assertEqual(marker.read_text(), "preserve")

    def test_legacy_cs137_reader_rejects_new_kind(self):
        p = self.config(); out = self.case / "new-kind"
        self.mock_prepare(p, out)
        with self.assertRaisesRegex(ValueError, "wrong prepared kind"):
            s.c.read_prepared(out)


if __name__ == "__main__":
    unittest.main()
