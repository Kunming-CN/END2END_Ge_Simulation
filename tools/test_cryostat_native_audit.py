"""Synthetic audit fixtures only: no CMake, Geant4, primaries or transport execution."""
import contextlib
import copy
import io
import json
import math
from pathlib import Path
import shutil
import stat
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import cryostat_native_audit as a

EVIDENCE = a.ROOT / a.BASE


def checkpoint(kind, timings):
    return {"kind": kind, "schema_version": 1, "status": "completed", "error": None,
            "runtime": {"geant4_version_number": 1132, "geant4_version": "synthetic fixture 11.3.2", "compiler": "fixture",
                        "cplusplus": 201703, "rng_engine": "fixture engine"},
            "geant4_version_number": 1132, "elapsed_seconds": 0.01, "stage_wall_seconds": {k: 0.001 for k in timings}}


def fixtures(facts):
    """Deliberately synthetic dimensions/material quantities, never native evidence."""
    solids = []
    for identifier, row in enumerate(facts["authored_solids"]):
        solids.append({"id": identifier, "name": row["name"], "entity_type": row["entity_type"], "constituents": [],
                       "moved_solid_id": None, "moved_rotation_object": None, "moved_rotation_frame": None,
                       "moved_translation_object_mm": None, "moved_translation_frame_mm": None})
    by_name = {r["name"]: r for r in solids}
    for i, edge in enumerate(facts["boolean_edges"]):
        identifier = 47 + i
        object_rotation = facts["source"]["holder_to_world"]["object_rotation"]
        translation = [1, 2, 3]
        solids.append({"id": identifier, "name": "fixture displaced helper", "entity_type": "G4DisplacedSolid", "constituents": [],
                       "moved_solid_id": by_name[edge["second"]]["id"], "moved_rotation_object": object_rotation,
                       "moved_rotation_frame": a.transpose(object_rotation), "moved_translation_object_mm": translation,
                       "moved_translation_frame_mm": [-v for v in a.mv(a.transpose(object_rotation), translation)]})
        by_name[edge["name"]]["constituents"] = [by_name[edge["first"]]["id"], identifier]
    custom = {r["name"]: r for r in facts["custom_materials"]}
    logicals = []
    for row in facts["logical_volumes"]:
        material = row["material"]
        if material in custom:
            counts = custom[material]["atomic_counts"]
            total = sum(counts.values())
            elements = [{"name": name, "symbol": name, "z": 1, "a_g_mole": 1, "mass_fraction": count / total}
                        for name, count in counts.items()]
            density = custom[material]["density_g_cm3"]
        else:
            elements = [{"name": "fixture", "symbol": "Au" if material == "G4_Au" else "fixture",
                         "z": 79 if material == "G4_Au" else 1, "a_g_mole": 1, "mass_fraction": 1}]
            density = 1
        logicals.append({**row, "solid_id": by_name[row["solid_name"]]["id"], "density_g_cm3": density, "elements": elements})
    physicals, physical_map = [], {}
    for row in sorted(facts["physical_identities"], key=lambda r: len(r["copy_chain"])):
        node = copy.deepcopy(row)
        object_rotation, translation = a.IDENTITY, [0, 0, 0]
        if node["path"] == "/lab/Holder":
            target = facts["source"]["holder_to_world"]
            object_rotation, translation = target["object_rotation"], target["translation_mm"]
        elif node["path"] == "/lab/Holder/Active":
            target = facts["source"]["active_to_holder"]
            object_rotation, translation = target["object_rotation"], target["translation_mm"]
        node.update(rotation_object_to_parent=object_rotation, rotation_frame=a.transpose(object_rotation),
                    translation_parent_mm=translation, translation_frame_mm=[-v for v in translation])
        if node["mother_path"] is None:
            node.update(rotation_object_to_global=object_rotation, translation_global_mm=translation)
        else:
            parent = physical_map[(node["mother_path"], tuple(node["copy_chain"][:-1]))]
            node.update(rotation_object_to_global=a.mm(parent["rotation_object_to_global"], object_rotation),
                        translation_global_mm=a.add(parent["translation_global_mm"], a.mv(parent["rotation_object_to_global"], translation)))
        physicals.append(node)
        physical_map[a.physical_key(node)] = node
    active = physical_map[("/lab/Holder/Active", (0, -5, -2))]
    imported = {**checkpoint("cryostat_native_import_v1", ["native_import", "census_materials_transforms"]),
                "logical_volumes": logicals, "physical_volumes": physicals, "solids": solids}
    geometry_solids = copy.deepcopy(solids)
    for row in geometry_solids:
        volume, valid, method, params = None, None, "not_applicable", {}
        if row["entity_type"] == "G4Box":
            params, volume, valid, method = {"half_lengths_mm": [1, 1, 1]}, 8, True, "analytic_primitive"
        elif row["entity_type"] == "G4Tubs":
            radius, height = (1.61, 0.001) if row["name"] == "Active" else (1, 1)
            params = {"inner_radius_mm": 0, "outer_radius_mm": radius, "half_length_mm": height,
                      "start_angle_rad": 0, "delta_angle_rad": 2 * math.pi}
            volume, valid, method = 2 * math.pi * radius * radius * height, True, "analytic_primitive"
        elif row["entity_type"] in ("G4UnionSolid", "G4SubtractionSolid"):
            method = "not_run_stochastic_boolean"
        row.update(bounding_min_mm=[-1, -1, -1], bounding_max_mm=[1, 1, 1], bounds_finite=True, bounds_ordered=True,
                   primitive_parameters=params, primitive_parameters_valid=valid, volume_mm3=volume, volume_method=method)
    probes = []
    for row in facts["probes"]:
        probes.append({**row, "global_mm": a.add(active["translation_global_mm"], a.mv(active["rotation_object_to_global"], row["source_local_mm"])),
                       "source_inside": row["expected_source_inside"]})
    geometry = {**checkpoint("cryostat_native_geometry_v1", ["solid_diagnostics", "overlaps"]), "solids": geometry_solids,
                "overlaps": [{"path": r["path"], "copy_chain": r["copy_chain"], "reported_overlap": False}
                             for r in physicals if r["mother_path"] is not None],
                "probes": probes, "overlap_seed": 26092632, "overlap_samples": 10000}
    positions = []
    for i in range(1000):
        local = [0.1 * math.sin(i), 0.1 * math.cos(i), 0.0005 * math.sin(i / 3)]
        positions.append({"index": i, "source_local_mm": local,
                          "global_mm": a.add(active["translation_global_mm"], a.mv(active["rotation_object_to_global"], local)),
                          "source_inside": "inside", "native_navigator_identity": {"name": "Active", "logical_name": "Active",
                          "path": "/lab/Holder/Active", "copy_chain": [0, -5, -2], "copy_number": -2}})
    gps = {**checkpoint("cryostat_native_gps_v1", ["gps_position_confinement"]),
           "original_settings": copy.deepcopy(facts["gps"]["original_settings"]), "native_getters": copy.deepcopy(facts["gps"]["native_getters"]),
           "seed": 26100161, "requested_positions": 1000, "positions": positions, "raw_internal_rejection_count_unknown": None}
    return {"import.json": imported, "geometry.json": geometry, "gps.json": gps}


def primitive_instance_fixtures(facts):
    """Reuse authored B origins as separate, referenced primitive instances."""
    reports = fixtures(facts)
    solids, geometry = reports["import.json"]["solids"], reports["geometry.json"]["solids"]
    by_name = {r["name"]: r for r in solids if r["entity_type"] != "G4DisplacedSolid"}
    by_id = {r["id"]: r for r in solids}
    geometry_ids = {r["id"]: r for r in geometry}
    repeated = set()
    for edge in facts["boolean_edges"]:
        origin = edge["second"]
        if by_name[origin]["entity_type"] not in ("G4Box", "G4Tubs"):
            continue
        if origin not in repeated:
            repeated.add(origin)
            continue
        original = by_name[origin]
        identifier = max(by_id) + 1
        instance = {**copy.deepcopy(original), "id": identifier}
        diagnostic = {**copy.deepcopy(geometry_ids[original["id"]]), "id": identifier}
        solids.append(instance); geometry.append(diagnostic); by_id[identifier] = instance
        helper_id = by_name[edge["name"]]["constituents"][1]
        by_id[helper_id]["moved_solid_id"] = identifier
        geometry_ids[helper_id]["moved_solid_id"] = identifier
    return reports


class NativeAuditTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.facts = a.expected()
        cls.reports = fixtures(cls.facts)

    def bad(self, reports, pattern):
        result = a.inspect_reports(reports, self.facts)
        self.assertFalse(result["scoped_acceptance"])
        self.assertRegex(" ".join(result["issues"]), pattern)

    def project(self, originals=False):
        temporary = tempfile.TemporaryDirectory(prefix="CONTROL-fixture-", dir=EVIDENCE)
        self.addCleanup(temporary.cleanup)
        root = Path(temporary.name)
        (root / a.BASE).mkdir(parents=True)
        for ref in a.SOURCES:
            path = root / ref
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(a.ROOT / ref, path)
        if originals:
            refs = [a.inputs.LEDGER_REF, a.inputs.MANIFEST_REF, "tools/check_cryostat_inputs.py", *a.LOCK_PINS]
            manifest = a.load(a.ROOT, a.inputs.MANIFEST_REF)
            refs += [".local/transport/LBNL/" + r["name"] for r in manifest["files"]]
            for ref in refs:
                if not (a.ROOT / ref).is_file():
                    self.skipTest("explicit original-byte cases need local recorded inputs")
                path = root / ref
                path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(a.ROOT / ref, path)
        a.freeze(root)
        return root

    def dummy_run(self, root, native_code=0, timeout=False, warning=False, build_code=0, changed_source=False, reports=None):
        calls = []
        def child(argv, **kwargs):
            runtime_text = (root / a.BASE / "CONTROL-RUNTIME.sh").read_text(encoding="utf-8")
            self.assertIn("--locked", runtime_text)
            self.assertIn("--no-install", runtime_text)
            self.assertNotIn("-c", argv)
            name = Path(kwargs["stdout"].name).name
            calls.append(name)
            versions = {"CONTROL-REMAGE-VERSION.stdout.log": "1.1.0", "CONTROL-GEANT4-VERSION.stdout.log": "11.3.2",
                        "CONTROL-CMAKE-VERSION.stdout.log": "cmake fixture", "CONTROL-COMPILER-VERSION.stdout.log": "compiler fixture",
                        "CONTROL-TIMEOUT-VERSION.stdout.log": "GNU timeout fixture"}
            if name in versions:
                kwargs["stdout"].write(versions[name].encode())
            if name == "CONTROL-BUILD.stdout.log":
                binary = root / a.BASE / "build/cryostat_native_audit"
                binary.parent.mkdir(parents=True, exist_ok=True)
                binary.write_bytes(b"synthetic fixture; never executable")
                if changed_source:
                    (root / a.SOURCES[0]).write_text("changed", encoding="utf-8")
                if build_code:
                    return subprocess.CompletedProcess(argv, build_code)
            if name == "CONTROL-NATIVE.stdout.log":
                native = root / a.BASE / "native"
                native.mkdir()
                selected = self.reports if reports is None else reports
                selected = selected if not timeout else {"import.json": selected["import.json"]}
                for stage, report in selected.items():
                    a.exclusive_json(native / stage, report)
                if warning:
                    kwargs["stderr"].write(b"*** G4Exception JustWarning: fixture confinement fallback")
                if timeout:
                    raise subprocess.TimeoutExpired(argv, 120)
                return subprocess.CompletedProcess(argv, native_code)
            return subprocess.CompletedProcess(argv, 0)
        with patch.object(a.subprocess, "run", side_effect=child):
            receipt = a.run(root)
        return receipt, calls

    def test_complete_synthetic_structure_and_all_position_checks(self):
        result = a.inspect_reports(self.reports, self.facts)
        self.assertEqual(result["status"], "complete_native_audit")
        self.assertEqual((result["logical_count"], result["physical_count"], result["native_solid_count"], result["gps_positions"]), (22, 23, 62, 1000))

    def test_all_primitive_origin_instances_are_referenced_and_equivalent(self):
        result = a.inspect_reports(primitive_instance_fixtures(self.facts), self.facts)
        self.assertTrue(result["scoped_acceptance"], result["issues"])
        self.assertEqual((result["authored_origin_count"], result["primitive_boolean_instance_count"],
                          result["displaced_helper_count"], result["native_solid_count"]), (47, 51, 15, 66))

    def test_unreferenced_copy_unknown_origin_and_boolean_duplicates_rejected(self):
        for name, expected in (("IRSub3", "unreferenced"), ("Stage", "duplicate Boolean")):
            reports = primitive_instance_fixtures(self.facts)
            extra = copy.deepcopy(next(r for r in reports["import.json"]["solids"] if r["name"] == name))
            extra["id"] = 999
            reports["import.json"]["solids"].append(extra)
            self.bad(reports, expected)
        reports = primitive_instance_fixtures(self.facts)
        reports["import.json"]["solids"][-1]["name"] = "invented origin"
        self.bad(reports, "unknown extra.*origin")
        reports = primitive_instance_fixtures(self.facts)
        reports["import.json"]["solids"][-1]["entity_type"] = "G4Box"
        self.bad(reports, "origin/type")

    def test_same_origin_instance_parameters_and_bounds_must_agree(self):
        for field in ("primitive_parameters", "bounding_max_mm"):
            reports = primitive_instance_fixtures(self.facts)
            row = reports["geometry.json"]["solids"][-1]
            if field == "primitive_parameters":
                row[field]["outer_radius_mm"] = 1.1
                row["volume_mm3"] = 2 * math.pi * 1.1 ** 2
            else:
                row[field][0] = 1.1
            self.bad(reports, "same-origin primitive")

    def test_logical_cached_primitive_cannot_gain_an_extra_instance(self):
        reports = primitive_instance_fixtures(self.facts)
        solids = reports["import.json"]["solids"]
        detector = next(r for r in solids if r["name"] == "Detector")
        extra = {**copy.deepcopy(detector), "id": 999}
        solids.append(extra)
        wings = next(r for r in solids if r["name"] == "Wings")
        helper = next(r for r in solids if r["id"] == wings["constituents"][1])
        helper["moved_solid_id"] = 999
        self.bad(reports, "cached logical solid origin")

    def test_manual_freeze_copies_all_nine_exact_sources(self):
        root = self.project()
        freeze = a.load(root, a.BASE + "/SOURCE-FREEZE.json")
        for ref, record in freeze["source_records"].items():
            self.assertEqual(a.pin(root, a.BASE + "/source-frozen/" + ref), record)
        self.assertEqual(len(freeze["source_records"]), 9)
        with self.assertRaisesRegex(a.AuditError, "no-clobber"): a.freeze(root)

    def historical_fixture(self):
        root = self.project(originals=True)
        receipt, _ = self.dummy_run(root, reports=primitive_instance_fixtures(self.facts), warning=True)
        receipt["inspection"] = {"status": "failed_native_audit", "scoped_acceptance": False,
                                 "issues": ["historical authored uniqueness failure"]}
        (root / a.BASE / "CONTROL-RUN.json").write_text(json.dumps(receipt), encoding="utf-8")
        pinned = a.pin(root, a.BASE + "/CONTROL-RUN.json")
        path = root / "tools/cryostat_native_audit.py"
        path.write_bytes(path.read_bytes() + b"\n# derived verifier fixture comment\n")
        return root, pinned

    def test_saved_reinspection_retains_original_failure_warnings_and_no_child(self):
        root, pinned = self.historical_fixture()
        with patch.object(a.subprocess, "run") as child:
            report = a.reinspect(root, pinned["sha256"])
        child.assert_not_called()
        self.assertEqual(a.pin(root, a.BASE + "/CONTROL-RUN.json"), pinned)
        self.assertEqual(report["original_inspection"]["status"], "failed_native_audit")
        self.assertEqual(report["status"], "completed_with_native_warnings")
        self.assertFalse(report["scoped_acceptance"])
        self.assertEqual(report["inspection"]["gps_positions"], 1000)
        self.assertTrue(all(status == "passed" for status in report["inspection"]["stages"].values()))
        self.assertEqual(report["native_invocations_this_call"], 0)
        self.assertNotEqual(report["verifier_source_records"], report["historical_source_records"])
        with self.assertRaisesRegex(a.AuditError, "frozen source"): a.verify(root)

    def test_reinspection_rejects_rehashed_receipt_wrong_native_and_snapshot(self):
        for change, expected in (("receipt", "receipt SHA256"), ("native", "native/expected identity"),
                                 ("snapshot", "historical source snapshot"), ("checkpoint", "checkpoint bytes")):
            root, pinned = self.historical_fixture()
            if change == "receipt":
                receipt = a.load(root, a.BASE + "/CONTROL-RUN.json")
                receipt["native_invocations"] = 0
                (root / a.BASE / "CONTROL-RUN.json").write_text(json.dumps(receipt), encoding="utf-8")
            else:
                ref = {"native": "tools/native_cryostat_audit/audit.cc", "snapshot": a.BASE + "/source-frozen/.gitattributes",
                       "checkpoint": a.BASE + "/native/geometry.json"}[change]
                path = root / ref
                path.write_bytes(path.read_bytes() + b" \n")
            with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, expected):
                a.reinspect(root, pinned["sha256"])
            child.assert_not_called()
        with self.assertRaisesRegex(a.AuditError, "external exact"): a.reinspect(root)

    def test_expected_rehashed_tampering_does_not_grant_support(self):
        root = self.project()
        value = copy.deepcopy(self.facts)
        value["census"]["physical_count_including_world"] = 20
        (root / a.EXPECTED).write_text(json.dumps(value), encoding="utf-8")
        self.assertNotEqual(a.inputs.digest(value), a.EXPECTED_DIGEST)
        with self.assertRaisesRegex(a.AuditError, "facts changed"):
            a.expected(root)

    def test_duplicate_nonfinite_invalid_json_and_types(self):
        for data in (b'{"x":1,"x":2}', b'{"x":NaN}', b'{"x":1e999}'):
            with self.assertRaises(a.AuditError):
                a.inputs.parse_json(data)
        reports = copy.deepcopy(self.reports)
        reports["gps.json"]["native_getters"]["confined"] = 1
        self.bad(reports, "type/value")
        reports = copy.deepcopy(self.reports)
        reports["gps.json"]["positions"][0]["global_mm"][0] = float("nan")
        self.bad(reports, "nonfinite")

    def test_geometry_and_gps_integer_identity_aliases_rejected(self):
        cases = (("geometry_id_bool", False), ("geometry_id_float", 0.0),
                 ("constituent_bool", True), ("constituent_float", 1.0),
                 ("moved_id_float", None), ("copy_chain_bool", False),
                 ("copy_chain_float", 0.0), ("copy_number_float", -2.0))
        for name, value in cases:
            with self.subTest(case=name):
                reports = copy.deepcopy(self.reports)
                if name.startswith("geometry_id"):
                    next(row for row in reports["geometry.json"]["solids"] if row["id"] == 0)["id"] = value
                elif name.startswith("constituent"):
                    row = next(row for row in reports["geometry.json"]["solids"] if row["constituents"] and row["constituents"][0] == 1)
                    row["constituents"][0] = value
                elif name == "moved_id_float":
                    row = next(row for row in reports["geometry.json"]["solids"] if row["entity_type"] == "G4DisplacedSolid")
                    row["moved_solid_id"] = float(row["moved_solid_id"])
                else:
                    navigator = reports["gps.json"]["positions"][0]["native_navigator_identity"]
                    if name.startswith("copy_chain"):
                        navigator["copy_chain"][0] = value
                    else:
                        navigator["copy_number"] = value
                self.bad(reports, "ID type|integer type")

    def test_wrong_counts_name_copy_and_material(self):
        edits = [("logical", "name", "active"), ("physical", "copy_number", 0), ("logical", "material", "AmO2")]
        for kind, key, value in edits:
            reports = copy.deepcopy(self.reports)
            rows = reports["import.json"]["logical_volumes" if kind == "logical" else "physical_volumes"]
            next(r for r in rows if r["name"] == "Active")[key] = value
            with self.subTest(kind=kind, key=key):
                self.bad(reports, "census|copy|material")
        reports = copy.deepcopy(self.reports)
        reports["import.json"]["physical_volumes"].pop()
        self.bad(reports, "census")

    def test_both_solder_ancestry_copy_identities_survive(self):
        reports = copy.deepcopy(self.reports)
        solder = [r for r in reports["import.json"]["physical_volumes"] if r["name"] == "Solder"]
        self.assertEqual({r["copy_number"] for r in solder}, {-20, -21})
        solder[1]["copy_chain"] = solder[0]["copy_chain"]
        self.bad(reports, "duplicate")

    def test_no_filtering_unknown_helper_or_wrong_constituent(self):
        reports = copy.deepcopy(self.reports)
        extra = copy.deepcopy(reports["import.json"]["solids"][-1])
        extra["id"] = 999
        reports["import.json"]["solids"].append(extra)
        self.bad(reports, "census|unknown")
        reports = copy.deepcopy(self.reports)
        reports["import.json"]["solids"][-1]["moved_solid_id"] = 0
        self.bad(reports, "helper")

    def test_frame_rotations_and_two_translation_conventions(self):
        reports = copy.deepcopy(self.reports)
        holder = next(r for r in reports["import.json"]["physical_volumes"] if r["name"] == "Holder")
        holder["rotation_object_to_parent"] = holder["rotation_frame"]
        self.bad(reports, "mismatch")
        reports = copy.deepcopy(self.reports)
        helper = reports["import.json"]["solids"][-1]
        helper["moved_translation_frame_mm"] = [-v for v in helper["moved_translation_object_mm"]]
        self.bad(reports, "mismatch")
        reports = copy.deepcopy(self.reports)
        holder = next(r for r in reports["import.json"]["physical_volumes"] if r["name"] == "Holder")
        holder["translation_frame_mm"] = [-v for v in a.mv(holder["rotation_frame"], holder["translation_parent_mm"])]
        self.bad(reports, "mismatch")

    def test_source_composed_centre_and_returned_point_inverse(self):
        reports = copy.deepcopy(self.reports)
        next(r for r in reports["import.json"]["physical_volumes"] if r["name"] == "Active")["translation_global_mm"][0] = -37.077
        self.bad(reports, "mismatch")
        reports = copy.deepcopy(self.reports)
        reports["gps.json"]["positions"][0]["source_local_mm"][2] = 0.0006
        self.bad(reports, "mismatch")

    def test_source_inside_navigator_and_confinement_settings(self):
        for key, value in (("source_inside", "surface"), ("native_navigator_identity", None)):
            reports = copy.deepcopy(self.reports)
            reports["gps.json"]["positions"][0][key] = value
            self.bad(reports, "interior|missing")
        reports = copy.deepcopy(self.reports)
        reports["gps.json"]["native_getters"]["confine"] = "active"
        self.bad(reports, "GPS setting")

    def test_gps_counter_seed_and_duplicates(self):
        for key, value in (("requested_positions", 999), ("seed", 26100162), ("raw_internal_rejection_count_unknown", 0)):
            reports = copy.deepcopy(self.reports)
            reports["gps.json"][key] = value
            self.bad(reports, "seed/count/unknown")
        reports = copy.deepcopy(self.reports)
        reports["gps.json"]["positions"][1]["index"] = 0
        self.bad(reports, "duplicate")

    def test_unknown_missing_report_fields_and_runtime(self):
        for key in ("extra", "error"):
            reports = copy.deepcopy(self.reports)
            if key == "extra": reports["gps.json"][key] = True
            else: del reports["gps.json"][key]
            self.bad(reports, "unknown/missing")
        reports = copy.deepcopy(self.reports)
        reports["import.json"]["geant4_version_number"] = 1140
        self.bad(reports, "version")

    def test_boolean_null_diagnostics_are_not_missing_acceptance_gates(self):
        row = next(r for r in self.reports["geometry.json"]["solids"] if r["entity_type"] == "G4UnionSolid")
        self.assertIsNone(row["volume_mm3"])
        self.assertEqual(row["volume_method"], "not_run_stochastic_boolean")
        reports = copy.deepcopy(self.reports)
        next(r for r in reports["geometry.json"]["solids"] if r["entity_type"] == "G4UnionSolid")["volume_mm3"] = 0
        self.bad(reports, "remain null")

    def test_geometry_zero_bounds_primitive_and_overlap_failure_preserved(self):
        for field, value in (("bounding_max_mm", [-1, -1, -1]), ("volume_mm3", 0)):
            reports = copy.deepcopy(self.reports)
            reports["geometry.json"]["solids"][0][field] = value
            result = a.inspect_reports(reports, self.facts)
            self.assertEqual(result["status"], "completed_with_geometry_failures")
            self.assertFalse(result["scoped_acceptance"])
        reports = copy.deepcopy(self.reports)
        reports["geometry.json"]["overlaps"][0]["reported_overlap"] = True
        self.assertEqual(a.inspect_reports(reports, self.facts)["status"], "completed_with_geometry_failures")

    def test_partial_import_and_geometry_leave_unknowns_and_stages(self):
        imported = copy.deepcopy(self.reports["import.json"])
        imported.update(status="incomplete", error="fixture import error", logical_volumes=None, physical_volumes=None, solids=None)
        # Match the actual native exception checkpoint: later timing key absent.
        imported["stage_wall_seconds"].pop("census_materials_transforms")
        result = a.inspect_reports({"import.json": imported}, self.facts)
        self.assertIsNone(result["logical_count"])
        self.assertIsNone(result["gps_positions"])
        self.assertEqual(result["stages"]["gps_position_confinement"], "not_executed")
        self.assertIn("fixture import error", result["issues"])
        reports = copy.deepcopy(self.reports)
        reports["geometry.json"].update(status="completed_with_geometry_failures", overlaps=[])
        reports["geometry.json"]["stage_wall_seconds"]["overlaps"] = None
        reports["geometry.json"]["solids"][0]["bounding_max_mm"] = [-1, -1, -1]
        reports["gps.json"].update(status="incomplete", error="not executed", native_getters=None, positions=[])
        reports["gps.json"]["stage_wall_seconds"]["gps_position_confinement"] = None
        result = a.inspect_reports(reports, self.facts)
        self.assertEqual(result["status"], "completed_with_geometry_failures")
        self.assertEqual(result["stages"]["overlaps"], "not_executed")
        self.assertIsNone(result["gps_positions"])
        reports["geometry.json"].update(status="incomplete", error="bounds interrupted")
        reports["geometry.json"]["stage_wall_seconds"].pop("overlaps")
        result = a.inspect_reports(reports, self.facts)
        self.assertEqual(result["stages"]["solid_diagnostics"], "incomplete")
        self.assertFalse(result["scoped_acceptance"])
        reports["geometry.json"]["stage_wall_seconds"]["unknown_stage"] = 0.1
        self.bad(reports, "unknown stage")

    def test_manual_freeze_requires_no_private_ai_state_or_exits(self):
        root = self.project()
        self.assertFalse((root / a.BASE / "CONTROL-EXIT.json").exists())
        self.assertEqual(set(a.frozen_sources(root)), set(a.SOURCES))
        self.assertFalse((root / ".local/autonomy").exists())

    def test_file_bridge_preserves_argv_without_inline_shell_text(self):
        root = self.project()
        arguments = ["python", "probe.py", "space value", 'double"quote', "single'quote", "$HOME", ";literal", "", "a\\b"]
        argv = a.runtime_command(root, arguments)
        self.assertEqual(argv[-len(arguments):], arguments)
        self.assertNotIn("-c", argv)
        self.assertIn(a.BASE + "/CONTROL-RUNTIME.sh", argv)
        self.assertNotIn("-c", a.native_arguments())
        self.assertNotIn("-c", a.cleanup_arguments())
        records = a.write_helpers(root)
        self.assertEqual(set(records), set(a.HELPERS))
        for ref, script in a.HELPERS.items():
            self.assertEqual((root / ref).read_bytes(), script.encode("utf-8"))
            self.assertNotIn(b"\r", (root / ref).read_bytes())
        with self.assertRaisesRegex(a.AuditError, "no-clobber"): a.write_helpers(root)

    def test_rehashed_saved_helper_edit_rejected_without_child(self):
        root = self.project(originals=True)
        receipt, _ = self.dummy_run(root)
        ref = a.BASE + "/CONTROL-NATIVE.sh"
        (root / ref).write_text("#!/bin/bash\nexit 0\n", encoding="utf-8")
        receipt["helper_records"][ref] = a.pin(root, ref)
        (root / a.BASE / "CONTROL-RUN.json").write_text(json.dumps(receipt), encoding="utf-8")
        with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, "code-owned runtime helper"):
            a.verify(root)
        child.assert_not_called()

    def test_actual_native_v2_exit_shape_without_status(self):
        root = self.project()
        ref = a.BASE + "/NATIVE-EXIT-v2.json"
        record = {
            "kind": "m11f_native_writer_exit_v2", "no_more_source_writes": True,
            "agent_path": "/root/m11f_native_builder", "schema_changed": False,
            "source_files": [{"path": p, **a.pin(root, p), "line_endings": "LF", "utf8_bom": False}
                             for p in ("tools/native_cryostat_audit/CMakeLists.txt", "tools/native_cryostat_audit/audit.cc")],
            "native_execution_count": 0, "cmake_configure_count": 0, "compile_count": 0,
        }
        freeze = a.load(root, a.BASE + "/SOURCE-FREEZE.json")
        for change, valid in (({}, True), ({"status": "exited"}, True), ({"status": "running"}, False),
                              ({"no_more_source_writes": False}, False), ({"kind": "unknown"}, False)):
            (root / ref).write_text(json.dumps({**record, **change}), encoding="utf-8")
            freeze["writer_exits"] = {"native": {"path": ref, "sha256": a.pin(root, ref)["sha256"]}}
            (root / a.BASE / "SOURCE-FREEZE.json").write_text(json.dumps(freeze), encoding="utf-8")
            if valid:
                self.assertEqual(set(a.frozen_sources(root)), set(a.SOURCES))
            else:
                with self.assertRaises(a.AuditError): a.frozen_sources(root)

    def test_changed_frozen_source_rejects_without_build_or_solver(self):
        root = self.project()
        (root / a.SOURCES[0]).write_text("changed", encoding="utf-8")
        with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, "frozen source"):
            a.run(root)
        child.assert_not_called()

    def test_original_byte_edit_even_if_external_metadata_rehashed(self):
        root = self.project(originals=True)
        path = root / ".local/transport/LBNL/LBNLcryostat.tg"
        path.write_bytes(path.read_bytes().replace(b':P CapID 67.7', b':P CapID 90.0'))
        with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, "original bytes"):
            a.run(root)
        child.assert_not_called()

    def test_fresh_exact_root_no_clobber_and_link_guard(self):
        root = self.project()
        for ref in (".local/m2a/new", ".local/elsewhere/build", a.BASE + "/../old"):
            with self.assertRaises(a.AuditError): a.new_path(root, ref)
        (root / a.BASE / "build").mkdir()
        with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, "no-clobber"):
            a.run(root)
        child.assert_not_called()
        target = root / a.BASE / "native"
        original = Path.lstat
        def reparse(path, **kwargs):
            if path == target:
                class Info:
                    st_mode = stat.S_IFDIR
                    st_file_attributes = stat.FILE_ATTRIBUTE_REPARSE_POINT
                return Info()
            return original(path, **kwargs)
        with patch.object(Path, "lstat", reparse), self.assertRaisesRegex(a.AuditError, "linked output"):
            a.new_path(root, a.BASE + "/native")

    def test_one_mocked_native_and_saved_verify_never_invokes_child(self):
        root = self.project(originals=True)
        receipt, calls = self.dummy_run(root)
        self.assertTrue(receipt["inspection"]["scoped_acceptance"])
        self.assertEqual(calls.count("CONTROL-NATIVE.stdout.log"), 1)
        with patch.object(a.subprocess, "run") as child:
            self.assertEqual(a.verify(root), receipt)
        child.assert_not_called()
        with self.assertRaises(a.AuditError): a.run(root)

    def test_build_and_child_failures_remain_exact_without_retry(self):
        root = self.project(originals=True)
        receipt, calls = self.dummy_run(root, build_code=7)
        self.assertEqual(receipt["commands"]["BUILD"]["return_code"], 7)
        self.assertEqual(receipt["native_invocations"], 0)
        self.assertNotIn("CONTROL-NATIVE.stdout.log", calls)
        root = self.project(originals=True)
        receipt, calls = self.dummy_run(root, native_code=-11)
        self.assertFalse(receipt["inspection"]["scoped_acceptance"])
        self.assertEqual(receipt["commands"]["NATIVE"]["return_code"], -11)
        self.assertEqual(calls.count("CONTROL-NATIVE.stdout.log"), 1)

    def test_native_timeout_retains_import_and_unknown_gps(self):
        root = self.project(originals=True)
        receipt, calls = self.dummy_run(root, timeout=True)
        self.assertEqual(receipt["inspection"]["status"], "timed_out_partial")
        self.assertIsNone(receipt["inspection"]["gps_positions"])
        self.assertEqual(set(receipt["checkpoint_records"]), {"import.json"})
        self.assertIn("CONTROL-NATIVE-CLEANUP.stdout.log", calls)
        timeout_script = (root / a.BASE / "CONTROL-NATIVE.sh").read_text(encoding="utf-8")
        self.assertIn("--signal=TERM --kill-after=5s 60s", timeout_script)

    def test_native_warning_blocks_blanket_acceptance(self):
        root = self.project(originals=True)
        receipt, _ = self.dummy_run(root, warning=True)
        self.assertEqual(receipt["inspection"]["status"], "completed_with_native_warnings")
        self.assertFalse(receipt["inspection"]["scoped_acceptance"])
        self.assertTrue(receipt["native_warning_or_error_log"])

    def test_changed_source_during_mocked_build_is_preserved(self):
        root = self.project(originals=True)
        receipt, calls = self.dummy_run(root, changed_source=True)
        self.assertIn("frozen source", receipt["error"])
        self.assertEqual(receipt["native_invocations"], 0)

    def test_rehashed_saved_wrong_source_frame_still_rejected(self):
        root = self.project(originals=True)
        receipt, _ = self.dummy_run(root)
        report_path = root / a.BASE / "native/gps.json"
        value = a.load(root, a.BASE + "/native/gps.json")
        value["positions"][0]["source_local_mm"][2] = 0.0006
        report_path.write_text(json.dumps(value), encoding="utf-8")
        receipt["checkpoint_records"]["gps.json"] = a.pin(root, a.BASE + "/native/gps.json")
        (root / a.BASE / "CONTROL-RUN.json").write_text(json.dumps(receipt), encoding="utf-8")
        with patch.object(a.subprocess, "run") as child, self.assertRaisesRegex(a.AuditError, "interpretation"):
            a.verify(root)
        child.assert_not_called()

    def test_portable_preflight_reads_no_private_originals(self):
        with patch.object(a.subprocess, "run") as child, patch.object(a, "consumed_inputs") as private:
            output = io.StringIO()
            with contextlib.redirect_stdout(output): self.assertEqual(a.main(["check", "--json"]), 0)
            self.assertEqual(json.loads(output.getvalue())["native_invocations"], 0)
        child.assert_not_called()
        private.assert_not_called()


if __name__ == "__main__":
    unittest.main(verbosity=2)
