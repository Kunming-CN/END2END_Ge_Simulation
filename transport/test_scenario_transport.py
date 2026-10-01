"""Retained synthetic HDF5 and mocked dispatch tests; never launch native science."""
import copy
import json
from pathlib import Path
import sys
import time
import types
import unittest
from unittest.mock import patch

import h5py
import numpy as np
import scenario_transport as t
import test_scenario_prepare as preparation_fixture

s, h = t.s, t.h


def dataset(group, name, values, integer=False, unit="", string=False):
    dtype = h5py.string_dtype("utf-8") if string else (np.int32 if integer else np.float64)
    ds = group.create_dataset(name, data=np.asarray(values, dtype=dtype))
    ds.attrs["units"] = unit


def raw_fixture(path, meta):
    """Twenty invented primaries, three Ge rows (one zero), one passive row."""
    source_m = np.asarray(meta["source_position_global_mm"], dtype=np.float64) / 1000
    bulk_m = h.to_global([10, 0, 5], meta["coordinate_transform"])
    with h5py.File(path, "w") as raw:
        raw.create_dataset("number_of_simulated_events", data=np.int32(20))
        origin = raw.create_group("detector_origins")
        origin.attrs["datatype"] = "table{name,xloc,yloc,zloc}"
        dataset(origin, "name", ["germanium"], string=True)
        del origin["name"].attrs["units"]  # Native string column has no units attribute.
        for axis, value in zip(("xloc", "yloc", "zloc"), meta["coordinate_transform"]["translation_global_mm"]):
            dataset(origin, axis, [value / 1000], unit="m")
        v, p, tr, proc, stp = (raw.create_group(name) for name in ("vtx", "particles", "tracks", "processes", "stp"))
        for group, keys in ((v, {"evtid": range(20), "n_part": [1]*20}),
                            (p, {"evtid": range(20), "vertexid": [0]*20, "particle": [22]*20})):
            for key, vals in keys.items():
                dataset(group, key, vals, integer=True)
        dataset(v, "time", [0]*20, unit="ns")
        for axis, value in zip(("xloc", "yloc", "zloc"), source_m):
            dataset(v, axis, [value]*20, unit="m")
        for key, value in {"ekin": .662, "px": 0, "py": -.662, "pz": 0}.items():
            dataset(p, key, [value]*20, unit="MeV")
        ids = [0, 0, *range(1, 20)]
        integers = {"evtid": ids, "particle": [22, 11, *([22]*19)], "trackid": [1, 2, *([1]*19)],
                    "parent_trackid": [0, 1, *([0]*19)], "procid": [-1, 1, *([-1]*19)]}
        for key, vals in integers.items():
            dataset(tr, key, vals, integer=True)
        for key, value in {"ekin": .662, "px": 0, "py": -.662, "pz": 0}.items():
            vals = [value]*21; vals[1] = .1 if key in ("ekin", "px") else 0
            dataset(tr, key, vals, unit="MeV")
        dataset(tr, "time", [0, .02, *([0]*19)], unit="ns")
        for axis, initial, bulk in zip(("xloc", "yloc", "zloc"), source_m, bulk_m):
            vals = [initial]*21; vals[1] = bulk
            dataset(tr, axis, vals, unit="m")
        dataset(proc, "procid", [0, 1], integer=True)
        dataset(proc, "name", ["Transportation", "compt"], string=True)
        for table in meta["material_tables"]:
            group = stp.create_group(table.split("/")[1])
            ge = table == "stp/germanium"
            count = 3 if ge else (1 if table == "stp/ledger_1" else 0)
            eids = [0, 1, 2] if ge else ([0] if count else [])
            for key, vals in {"evtid": eids, "particle": ([11, 22, 22] if ge else [22]*count),
                    "trackid": ([2, 1, 1] if ge else [1]*count),
                    "parent_trackid": ([1, 0, 0] if ge else [0]*count)}.items():
                dataset(group, key, vals, integer=True)
            dataset(group, "edep", ([100.125, 0, 50.25] if ge else [3.0625]*count), unit="keV")
            dataset(group, "time", [.1]*count, unit="ns")
            for suffix in ("", "_pre", "_post"):
                for axis, value in zip(("xloc", "yloc", "zloc"), bulk_m):
                    dataset(group, axis + suffix, [value]*count, unit="m")
                if ge:
                    dataset(group, "dist_to_surf" + suffix, [.001]*count, unit="m")
        aliases = stp.create_group("__by_uid__")
        for uid, target in t.UIDS.items():
            aliases[uid] = h5py.SoftLink(target)


class GammaTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        root = s.ROOT / ".local/m11b-gamma20-v1/mock-tests"
        root.mkdir(parents=True, exist_ok=True)
        for number in range(1, 10000):
            candidate = root / ("run-" + str(number))
            try:
                candidate.mkdir()
                cls.bundle = candidate
                break
            except FileExistsError:
                continue
        else:
            raise RuntimeError("finite fixture reservation exhausted")
        cls.start, cls.case_count = time.perf_counter(), 0

    @classmethod
    def tearDownClass(cls):
        h.publish_json(cls.bundle / "fixture-receipt.json", {"kind": "synthetic_hdf5_mocked_gamma_tests",
            "case_count": cls.case_count, "wall_s": time.perf_counter() - cls.start,
            "versions": h.python_versions(), "native_geometry_calls": 0, "native_radiation_calls": 0,
            "ssd_readout_calls": 0, "fixtures_retained": True})

    def setUp(self):
        type(self).case_count += 1
        self.case = self.bundle / ("case-" + str(self.case_count))
        self.case.mkdir()
        self.number = 0

    def prepared(self, model="AK02"):
        self.number += 1
        directory = self.case / (model + "-" + str(self.number))
        config = s.ROOT / f"scenarios/m11a-{model.lower()}-mono_gamma_662_axis_v1-plus5mm.json"
        plan = s.check(config)
        report = preparation_fixture.report_fixture(plan)
        def mock_export(command, **kwargs):
            Path(command[-2]).write_text("<gdml><!-- SYNTHETIC UNIT FIXTURE --></gdml>\n", encoding="utf-8")
            Path(command[-1]).write_text(h.json_text(report), encoding="utf-8")
            kwargs["stdout"].write("Synthetic mocked exporter; no native execution.\n")
            return types.SimpleNamespace(returncode=0)
        with patch.object(s.subprocess, "run", side_effect=mock_export) as dispatch:
            s.prepare(config, directory, s.ROOT / ".local/m2a/cs137-build-v1/cryostat_export")
            self.assertEqual(dispatch.call_count, 1)
        return directory

    def raw(self, model="AK02"):
        self.number += 1
        path = self.case / ("fixture-" + str(self.number) + ".lh5")
        plan = s.check(s.ROOT / f"scenarios/m11a-{model.lower()}-mono_gamma_662_axis_v1-plus5mm.json")
        _, points = h.load_model(model)
        meta = {"source_position_global_mm": plan["source_position_global_mm"],
                "coordinate_transform": plan["coordinate_transform"], "contour_rz_mm": points,
                "material_tables": {"stp/" + e[0]: e[3] for e in s.LEDGER if e[0] != "ledger_0_PV"}}
        raw_fixture(path, meta)
        return path, meta

    def changed_meta(self, directory, change):
        meta = s.strict_load(directory / "prepared.json")
        change(meta)
        (directory / "prepared.json").write_text(h.json_text(meta), encoding="utf-8")

    def package(self):
        self.number += 1
        base = self.case / ("emlow-fixture-" + str(self.number))
        base.mkdir(); (base / "gamma.dat").write_bytes(b"synthetic gamma dependency fixture\n")
        pkg = self.case / ("emlow-package-" + str(self.number) + ".json")
        pkg.write_text(h.json_text({"name": "geant4-data-emlow", "version": "8.6.1", "build": "hd8ed1ab_0", "sha256": t.EMLOW_ARCHIVE}), encoding="utf-8")
        manifest = self.case / ("emlow-data-" + str(self.number) + ".json")
        h.publish_json(manifest, t.emlow_manifest(base, pkg))
        return {"versions": {"remage": "MOCK ONLY", "geant4-config": "MOCK ONLY"},
            "emlow_manifest": str(manifest), "emlow_manifest_sha256": h.sha256(manifest)}

    def successful_mock_run(self, directory, mutate=None):
        meta = s.strict_load(directory / "prepared.json")
        runtime = self.package()
        def dispatch(command, **kwargs):
            self.assertEqual(command, t.COMMAND)
            self.assertIs(kwargs["shell"], False)
            self.assertEqual(kwargs["cwd"], directory)
            raw_fixture(directory / "truth.lh5", meta)
            if mutate:
                mutate(directory / "truth.lh5")
            kwargs["stdout"].write("Synthetic mocked remage; no native execution.\n")
            return types.SimpleNamespace(returncode=0)
        with patch.object(t, "runtime", return_value=runtime), patch.object(t.subprocess, "run", side_effect=dispatch) as call:
            record = t.run(directory)
            self.assertEqual(call.call_count, 1)
        return record

    def test_both_models_all_primary_ids_zero_and_complete_rows(self):
        for model in ("AK02", "SAP22"):
            with self.subTest(model=model):
                path, meta = self.raw(model)
                events = list(t.iter_events(path, meta))
                self.assertEqual([e["event_id"] for e in events], list(range(20)))
                self.assertEqual([e["initial_primary_id"] for e in events], list(range(20)))
                self.assertEqual(sum(e["zero_ge"] for e in events), 18)
                self.assertEqual(events[1]["truth_ge_edep_keV"], 0)
                self.assertEqual(len(events[1]["steps"]), 1)
                self.assertEqual([e["steps"][0]["raw_row_index"] for e in events[:3]], [0, 1, 2])
                self.assertEqual(events[0]["tracks"][0]["procid"], -1)
                self.assertEqual(events[0]["tracks"][1]["parent_trackid"], 1)
                self.assertEqual(len(events[0]["material_rows"]), 19)
                self.assertEqual(events[0]["material_energy_keV"]["G4_Al"], 3.0625)
                self.assertEqual(t.validate_actual_probe(path, meta), {"initial_gamma_primaries": 20,
                    "zero_ge_primaries": 18, "ge_raw_rows": 3, "all_material_raw_rows": 4})
                for eid in range(3):
                    np.testing.assert_allclose(events[eid]["steps"][0]["position_mm"], [10, 0, 5], rtol=0, atol=1e-12)
                # All native scalar fields, including surface distances, survive unchanged.
                with h5py.File(path, "r") as raw:
                    expected = list(t.c.table_rows(raw["stp/germanium"]))
                self.assertEqual([e["material_rows"]["stp/germanium"][0] for e in events[:3]], expected)

    def test_gamma_primary_negative_identity_energy_direction_clock_and_position(self):
        edits = [("particles/particle", 1000551370), ("particles/ekin", 662), ("particles/py", .662),
                 ("particles/px", .001), ("vtx/time", 1), ("vtx/n_part", 2), ("particles/vertexid", 1),
                 ("vtx/yloc", .037073), ("vtx/zloc", .290), ("tracks/py", .662)]
        for field, value in edits:
            with self.subTest(field=field, value=value):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw:
                    raw[field][0] = value
                with self.assertRaises(ValueError):
                    list(t.iter_events(path, meta))

    def test_missing_foreign_duplicate_event_and_wrong_census(self):
        for field, index, value in (("vtx/evtid", 1, 0), ("particles/evtid", 19, 20),
                                    ("tracks/evtid", 20, 0), ("number_of_simulated_events", (), 19)):
            with self.subTest(field=field):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw:
                    raw[field][index] = value
                with self.assertRaises(ValueError):
                    list(t.iter_events(path, meta))

    def test_alias_and_material_absence_are_not_zero(self):
        for mode in ("absent-material", "absent-aliases", "duplicate-target", "wrong-uid", "hard-link"):
            with self.subTest(mode=mode):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw:
                    if mode == "absent-material":
                        del raw["stp/ledger_2"]
                    elif mode == "absent-aliases":
                        del raw["stp/__by_uid__"]
                    else:
                        aliases = raw["stp/__by_uid__"]; del aliases["det002"]
                        if mode == "duplicate-target": aliases["det002"] = h5py.SoftLink("/stp/germanium")
                        elif mode == "wrong-uid": aliases["det001"] = h5py.SoftLink("/stp/ledger_1")
                        else: aliases["det002"] = raw["stp/ledger_1"]
                with self.assertRaises(ValueError):
                    list(t.iter_events(path, meta))

    def test_global_single_ge_origin_schema_units_type_name_and_pose(self):
        path, meta = self.raw()
        with h5py.File(path, "r") as raw:
            rows = t.detector_origins(raw, meta)
            self.assertEqual(rows[0]["raw_row_index"], 0)
            self.assertEqual(rows[0]["name"], "germanium")
            self.assertNotIn("evtid", rows[0])
        for mode in ("missing", "name", "translation", "mm", "units", "float32", "datatype", "extra-root", "duplicate"):
            with self.subTest(mode=mode):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw:
                    group = raw["detector_origins"]
                    if mode == "missing": del raw["detector_origins"]
                    elif mode == "extra-root": raw.create_group("arbitrary")
                    elif mode == "name": group["name"][0] = "ledger_17"
                    elif mode == "translation": group["yloc"][0] = .00645
                    elif mode == "mm": group["yloc"][0] = 1.45
                    elif mode == "units": group["yloc"].attrs["units"] = "mm"
                    elif mode == "datatype": group.attrs["datatype"] = "table{evtid,name,xloc,yloc,zloc}"
                    elif mode == "float32":
                        vals = group["yloc"][:]; del group["yloc"]
                        ds = group.create_dataset("yloc", data=vals.astype(np.float32)); ds.attrs["units"] = "m"
                    else:
                        for key in list(group):
                            vals = group[key][:]; dtype = group[key].dtype; attrs = dict(group[key].attrs)
                            del group[key]; ds = group.create_dataset(key, data=np.concatenate([vals, vals]), dtype=dtype)
                            for k, v in attrs.items(): ds.attrs[k] = v
                with self.assertRaises(ValueError): list(t.iter_events(path, meta))

    def test_wrong_units_float_precision_boolean_ids_and_nonfinite_refuse(self):
        for mode in ("units", "float32", "bool", "nan", "infinity", "extra-column"):
            with self.subTest(mode=mode):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw:
                    ds = raw["particles/ekin"]
                    if mode == "units": ds.attrs["units"] = "keV"
                    elif mode in ("float32", "bool"):
                        name = "ekin" if mode == "float32" else "particle"
                        vals = raw["particles/" + name][:]; unit = raw["particles/" + name].attrs["units"]
                        del raw["particles/" + name]
                        new = raw["particles"].create_dataset(name, data=vals.astype(np.float32 if mode == "float32" else bool)); new.attrs["units"] = unit
                    elif mode == "extra-column": dataset(raw["particles"], "secret", [0]*20)
                    else: ds[0] = float("nan" if mode == "nan" else "inf")
                with self.assertRaises(ValueError):
                    list(t.iter_events(path, meta))

    def test_track_ancestry_and_process_creation_refuse(self):
        for field, index, value in (("tracks/trackid", 1, 1), ("tracks/parent_trackid", 1, 2),
                ("tracks/parent_trackid", 1, 99), ("tracks/procid", 1, 99), ("tracks/time", 1, -.1),
                ("stp/germanium/particle", 0, 22), ("stp/germanium/parent_trackid", 0, 0),
                ("stp/germanium/trackid", 0, 99), ("stp/germanium/time", 0, .001),
                ("stp/germanium/edep", 0, -1), ("processes/procid", 1, 0)):
            with self.subTest(field=field):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw: raw[field][index] = value
                with self.assertRaises(ValueError): list(t.iter_events(path, meta))

    def test_metres_to_mm_and_ge_endpoint_containment(self):
        for field, value in (("stp/germanium/xloc", 10), ("stp/germanium/zloc_pre", 1), ("stp/germanium/yloc_post", 1)):
            with self.subTest(field=field):
                path, meta = self.raw()
                with h5py.File(path, "r+") as raw: raw[field][0] = value
                with self.assertRaises(ValueError): list(t.iter_events(path, meta))

    def test_prepared_exact_public_gamma_binding_both_models(self):
        for model in ("AK02", "SAP22"):
            directory = self.prepared(model)
            with patch.object(t.subprocess, "run", side_effect=AssertionError("no dispatch during check")):
                _, meta, _ = t.read_prepared(directory)
            self.assertEqual(meta["assets"]["detector"]["temperature_K"], 78)
            self.assertEqual(meta["assets"]["detector"]["contacts"][1]["potential_V"], 500 if model == "AK02" else 700)
            self.assertEqual(meta["source_position_global_mm"], [0, 42.073, .290])
            self.assertEqual(set(p.name for p in directory.iterdir()), t.PREP_FILES | {"prepared.json", "prepare-receipt.json"})

    def test_cold_cli_check_initializes_preparation_helpers_before_inventory(self):
        directory = self.prepared()
        before = {p.name: h.sha256(p) for p in directory.iterdir()}
        # A separate interpreter proves no prepare fixture or imported module
        # initialized scenario_prepare's deferred globals before the CLI check.
        code = """import sys, subprocess
import scenario_prepare as s
assert 'h' not in vars(s) and 'c' not in vars(s)
import scenario_transport as t
assert 'h' not in vars(s) and 'c' not in vars(s)
def refuse_native(*args, **kwargs):
    raise AssertionError('check must not dispatch native or runtime commands')
subprocess.run = refuse_native
sys.argv = ['scenario_transport.py', 'check', '--prepared', sys.argv[1]]
t.main()
"""
        child = t.subprocess.run([sys.executable, "-B", "-c", code, str(directory)], cwd=s.HERE,
            stdout=t.subprocess.PIPE, stderr=t.subprocess.PIPE, text=True, check=False, shell=False)
        (self.case / "cold-check-stdout.txt").write_text(child.stdout, encoding="utf-8")
        (self.case / "cold-check-stderr.txt").write_text(child.stderr, encoding="utf-8")
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(json.loads(child.stdout), {"kind": t.RUN_KIND, "status": "checked_only",
            "model_id": "AK02", "planned_primaries": 20})
        self.assertEqual(before, {p.name: h.sha256(p) for p in directory.iterdir()})

    def test_rehashed_bool_version_and_provenance_summary_refuse_before_dispatch(self):
        edits = [("schema_version", True), ("overlap_seed", True), ("overlap_samples", 9999),
                 ("unscored_volumes", []), ("material_tables", {"stp/germanium": "G4_Ge"}),
                 ("unknowns", []), ("activity_Bq", 0), ("energy_closure", 1)]
        for key, value in edits:
            with self.subTest(key=key):
                directory = self.prepared()
                self.changed_meta(directory, lambda m: m.__setitem__(key, value))
                before = {p.name: h.sha256(p) for p in directory.iterdir()}
                with patch.object(t.subprocess, "run") as call, patch.object(t, "runtime") as runtime:
                    with self.assertRaises(ValueError): t.run(directory)
                    call.assert_not_called(); runtime.assert_not_called()
                self.assertEqual(before, {p.name: h.sha256(p) for p in directory.iterdir()})

    def test_rehashed_macro_parameters_probes_and_report_semantics_refuse(self):
        for name in ("run.mac", "parameters.txt", "probe-points.txt", "geometry-report.json"):
            with self.subTest(name=name):
                directory = self.prepared()
                p = directory / name
                text = p.read_text(encoding="utf-8")
                if name == "run.mac": text = text.replace("/gps/direction 0 -1 0", "/gps/direction 0 1 0")
                elif name == "parameters.txt": text = "0 " + text
                elif name == "probe-points.txt": text = "0 0 0\n" + text
                else:
                    report = json.loads(text); report["overlaps_passed"] = False; text = h.json_text(report)
                p.write_text(text, encoding="utf-8")
                self.changed_meta(directory, lambda m: m["files_sha256"].__setitem__(name, h.sha256(p)))
                with patch.object(t.subprocess, "run") as call:
                    with self.assertRaises(ValueError): t.read_prepared(directory)
                    call.assert_not_called()

    def test_prepared_same_read_snapshot_hash_refuses_returned_wrong_witness(self):
        directory = self.prepared()
        snapshot = s.json_snapshot
        def wrong(path):
            obj, digest = snapshot(path)
            if Path(path).name == "resolved-instance.json": digest = "0"*64
            return obj, digest
        with patch.object(s, "json_snapshot", side_effect=wrong), patch.object(t.subprocess, "run") as call:
            with self.assertRaises(ValueError): t.read_prepared(directory)
            call.assert_not_called()

    def test_complete_plan_against_first_inventory_before_runtime_or_output(self):
        directory = self.prepared()
        real = s.frozen_inventory
        def changed(*args):
            result = real(*args)
            result["scenarios/m11a-ak02-mono_gamma_662_axis_v1-plus5mm.json"] = "0"*64
            return result
        with patch.object(s, "frozen_inventory", side_effect=changed), patch.object(t.subprocess, "run") as call:
            with self.assertRaises(ValueError): t.run(directory)
            call.assert_not_called()
        self.assertFalse((directory / "run.json").exists())

    def test_no_clobber_no_legacy_reader_no_julia_and_exact_macro(self):
        directory = self.prepared()
        with patch.object(t.c, "iter_decays", side_effect=AssertionError("legacy reader forbidden")), patch.object(t.c, "prepare_cs137", side_effect=AssertionError("legacy producer forbidden")):
            record = self.successful_mock_run(directory)
        self.assertEqual(record["status"], "complete")
        before = {p.name: h.sha256(p) for p in directory.iterdir()}
        with patch.object(t.subprocess, "run") as call:
            with self.assertRaises(ValueError): t.run(directory)
            call.assert_not_called()
        self.assertEqual(before, {p.name: h.sha256(p) for p in directory.iterdir()})
        macro = (directory / "run.mac").read_text()
        for line in ("/gps/particle gamma", "/gps/direction 0 -1 0", "/gps/ene/type Mono", "/gps/ene/mono 662 keV", "/gps/time 0 ns", "/gps/number 1", "/run/beamOn 20",
                     "/RMG/Output/Track/StoreAlways true", "/RMG/Output/Germanium/DiscardZeroEnergyHits false", "/RMG/Output/Vertex/StoreSinglePrecisionPosition false"):
            self.assertIn(line + "\n", macro)
        self.assertNotIn("/gps/ion", macro); self.assertNotIn("/RMG/Generator/Confinement", macro)

    def test_exit_zero_wrong_gamma_retains_failed_raw_and_receipt(self):
        directory = self.prepared()
        def bad(path):
            with h5py.File(path, "r+") as raw: raw["particles/py"][0] = .662
        with self.assertRaises(ValueError): self.successful_mock_run(directory, bad)
        record = s.strict_load(directory / "run.json")
        self.assertEqual(record["status"], "failed"); self.assertEqual(record["returncode"], 0)
        self.assertTrue((directory / "truth.lh5").exists()); self.assertTrue((directory / "run.log").exists())

    def test_native_exit_diagnostics_and_postdispatch_inputs_retain_failure(self):
        for mode in ("exit", "diagnostic", "input-changed"):
            with self.subTest(mode=mode):
                directory = self.prepared(); runtime = self.package()
                meta = s.strict_load(directory / "prepared.json")
                def dispatch(command, **kwargs):
                    raw_fixture(directory / "truth.lh5", meta)
                    kwargs["stdout"].write("*** Fatal simulated diagnostic\n" if mode == "diagnostic" else "Mock only\n")
                    if mode == "input-changed": (directory / "run.mac").write_text("changed after mocked dispatch\n")
                    return types.SimpleNamespace(returncode=7 if mode == "exit" else 0)
                with patch.object(t, "runtime", return_value=runtime), patch.object(t.subprocess, "run", side_effect=dispatch):
                    with self.assertRaises(ValueError): t.run(directory)
                self.assertEqual(s.strict_load(directory / "run.json")["status"], "failed")
                self.assertTrue((directory / "truth.lh5").exists())

    def test_changed_frozen_source_before_dispatch_retains_failed_receipt(self):
        directory = self.prepared()
        pins = t.producer_hashes(); runtime = self.package()
        with patch.object(t, "runtime", return_value=runtime), patch.object(t, "producer_hashes", side_effect=[pins, {**pins, "transport/scenario_transport.py": "0"*64}]), patch.object(t.subprocess, "run") as call:
            with self.assertRaises(ValueError): t.run(directory)
            call.assert_not_called()
        self.assertEqual(s.strict_load(directory / "run.json")["status"], "failed")
        self.assertFalse((directory / "truth.lh5").exists())

    def test_emlow_metadata_subtree_identity_and_changed_file_refuse(self):
        record = self.package()
        self.assertGreaterEqual(t.recheck_data(record), 0)
        saved = s.strict_load(Path(record["emlow_manifest"]))
        self.assertEqual(saved["file_count"], 1)
        (Path(saved["directory"]) / "gamma.dat").write_bytes(b"changed bytes")
        with self.assertRaises(ValueError): t.recheck_data(record)
        pkg = Path(saved["package_metadata"])
        obj = s.strict_load(pkg); obj["build"] = "different"; pkg.write_text(h.json_text(obj))
        with self.assertRaises(ValueError): t.emlow_manifest(saved["directory"], pkg)

    def test_missing_runtime_refuses_without_dispatch_and_keeps_attempt(self):
        directory = self.prepared()
        with patch.object(t.shutil, "which", return_value=None), patch.object(t.subprocess, "run") as call:
            with self.assertRaises(ValueError): t.run(directory)
            call.assert_not_called()
        self.assertEqual(s.strict_load(directory / "run.json")["status"], "failed")

    def test_full_extraction_float64_raw_provenance_and_no_overwrite(self):
        for model in ("AK02", "SAP22"):
            with self.subTest(model=model):
                directory = self.prepared(model); self.successful_mock_run(directory)
                manifest = t.extract(directory)
                self.assertEqual(manifest["kind"], t.KIND)
                self.assertEqual(manifest["primary_count"], 20)
                self.assertEqual(manifest["raw_tables"]["tracks"]["rows"], 21)
                self.assertEqual(manifest["raw_tables"]["stp/germanium"]["rows"], 3)
                self.assertEqual(manifest["raw_tables"]["particles"]["columns"]["ekin"], {"dtype": "float64", "units": "MeV", "attributes": {"units": "MeV"}})
                self.assertEqual(manifest["raw_tables"]["detector_origins"]["rows"], 1)
                self.assertEqual(manifest["raw_tables"]["detector_origins"]["attributes"], {"datatype": "table{name,xloc,yloc,zloc}"})
                self.assertEqual(manifest["raw_tables"]["detector_origins"]["columns"]["name"]["attributes"], {})
                self.assertEqual(len(manifest["detector_origins"]), 1)
                self.assertNotIn("event_id", manifest["detector_origins"][0])
                self.assertIsNone(manifest["ledger"]["full_energy_closure"])
                self.assertEqual(manifest["seed"], 26092631)
                self.assertEqual(manifest["stored_temperature_K"], 78)
                self.assertEqual(manifest["stages"]["charge"], "charge_not_executed")
                lines = (directory / "stream/events-00000000.jsonl").read_text().splitlines()
                expected = list(t.iter_events(directory / "truth.lh5", s.strict_load(directory / "prepared.json")))
                self.assertEqual([json.loads(line) for line in lines], expected)
                before = {p.name: h.sha256(p) for p in (directory / "stream").iterdir()}
                with self.assertRaises(ValueError): t.extract(directory)
                self.assertEqual(before, {p.name: h.sha256(p) for p in (directory / "stream").iterdir()})

    def test_rehashed_run_seed_returncode_and_census_refuse(self):
        for mode in ("seed", "bool-returncode", "census"):
            with self.subTest(mode=mode):
                directory = self.prepared(); self.successful_mock_run(directory)
                record = s.strict_load(directory / "run.json")
                if mode == "seed": record["command"][6] = "1"
                elif mode == "bool-returncode": record["returncode"] = False
                else: record["validation"]["initial_gamma_primaries"] = 19
                (directory / "run.json").write_text(h.json_text(record))
                with self.assertRaises(ValueError): t.extract(directory)
                if mode == "census":
                    self.assertTrue((directory / "stream/events-00000000.jsonl.partial").exists())
                    self.assertEqual(s.strict_load(directory / "stream/extract-receipt.json")["status"], "failed")
                else: self.assertFalse((directory / "stream").exists())

    def test_changed_raw_or_generated_input_refuses_before_derived_output(self):
        for mode in ("raw", "prepared"):
            with self.subTest(mode=mode):
                directory = self.prepared(); self.successful_mock_run(directory)
                if mode == "raw":
                    with h5py.File(directory / "truth.lh5", "r+") as raw: raw["stp/germanium/edep"][0] = 1
                else: (directory / "run.mac").write_text("changed source")
                with self.assertRaises(ValueError): t.extract(directory)
                self.assertFalse((directory / "stream").exists())

    def test_local_path_escape_and_completed_old_kind_refuse(self):
        with self.assertRaises(ValueError): t.read_prepared(s.ROOT / "transport")
        directory = self.prepared()
        self.changed_meta(directory, lambda m: m.__setitem__("kind", "cs137_cryo_prepared_v1"))
        with self.assertRaises(ValueError): t.read_prepared(directory)


if __name__ == "__main__":
    unittest.main(verbosity=2)
