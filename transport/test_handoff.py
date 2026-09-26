"""Pure tests only: no remage invocation, Geant4 build, or SSD physics claims.

Run: bash transport/run.sh python -B transport/test_handoff.py (from project root).
Temporary synthetic fixtures live below .local/m2a and are removed by unittest.
"""
import copy
import importlib.util
import json
import math
from pathlib import Path
import tempfile
import unittest
from subprocess import CompletedProcess
from unittest.mock import patch
import xml.etree.ElementTree as ET

import h5py
import numpy as np

import handoff as h

AK = [(0, 2.1), (7.8, 2.1), (7.8, 0), (12.65, 0), (12.65, 9.4),
      (7.75, 9.4), (7.75, 7.9), (2.95, 7.9), (2.95, 9.4), (0, 9.4), (0, 2.1)]
SAP = [(0, 4.2), (8.85, 4.2), (8.85, 0), (12.75, 0), (12.75, 10),
       (8.75, 10), (8.75, 7), (3.85, 7), (3.85, 10), (0, 10), (0, 4.2)]


def document(points=AK):
    return {"units": {"length": "mm", "angle": "deg", "potential": "V", "temperature": "K"},
            "medium": "vacuum", "grid": {"coordinates": "cylindrical"},
            "detectors": [{"semiconductor": {"material": "HPGe", "temperature": 78,
                           "geometry": {"polycone": {"r": [p[0] for p in points],
                                                      "z": [p[1] for p in points]}}},
                           "contacts": [{"potential": 0}, {"potential": 500}]}]}


def metadata():
    return {"model_id": "AK02", "model_sha256": h.PINNED["AK02"], "primary_count": 3,
            "seed": 260925, "energy_keV": 662, "coordinate_transform": copy.deepcopy(h.TRANSFORM),
            "contour_rz_mm": AK, "lock_sha256": h.sha256(h.ROOT / "transport/pixi.lock"),
            "files_sha256": {"geometry.gdml": "0" * 64, "run.mac": "1" * 64}}


def fixture(path, *, empty=False, transform=None):
    """Flat schema from remage 1.1.0; values are entirely synthetic.

    Event 0 has two deposits and a zero-energy row, event 1 has no hits,
    event 2 starts at 40 ns and has a 1040 ns delayed deposit. Input unsorted.
    """
    with h5py.File(path, "w") as f:
        f["number_of_simulated_events"] = np.int64(3)
        v = f.create_group("vtx")
        for name, values, unit in [
            ("evtid", [2, 0, 1], None), ("n_part", [1, 1, 1], None),
            ("time", [40., 0., 0.], "ns"), ("xloc", [.02] * 3, "m"),
            ("yloc", [0.] * 3, "m"), ("zloc", [.005] * 3, "m"),
        ]:
            v[name] = values
            if unit:
                v[name].attrs["units"] = unit
        prim = f.create_group("particles")
        for key, vals, unit in [
            ("evtid", [2,0,1], None), ("particle", [22,22,22], None), ("vertexid", [0,0,0], None),
            ("ekin", [.662]*3, "MeV"), ("px", [-.662]*3, "MeV"), ("py", [0.]*3, "MeV"), ("pz", [0.]*3, "MeV")]:
            prim[key] = vals
            if unit:
                prim[key].attrs["units"] = unit
        g = f.create_group(h.TABLE)
        columns = {"evtid": ([2, 0, 0, 0], None), "particle": ([11, 22, 11, 22], None),
                   "trackid": ([2, 1, 2, 1], None), "parent_trackid": ([1, 0, 1, 0], None),
                   "edep": ([3., 1.25, 2.5, 0.], "keV"), "time": ([1040., 1., 2., 3.], "ns")}
        for suffix in ("", "_pre", "_post"):
            xyz = np.tile([10., 0., 5.], (4, 1))
            xyz[:, 0] += {"": 0, "_pre": -.01, "_post": .01}[suffix]
            xyz = h.to_global(xyz, transform or h.TRANSFORM)
            for i, name in enumerate(("xloc", "yloc", "zloc")):
                columns[name + suffix] = (xyz[:, i], "m")
        columns["dist_to_surf"] = ([.002] * 4, "m")
        columns["unmapped_counter"] = ([5, 6, 7, 8], None)
        for name, (values, unit) in columns.items():
            arr = np.asarray(values)
            g[name] = arr[:0] if empty else arr
            if unit:
                g[name].attrs["units"] = unit


class GeometryTests(unittest.TestCase):
    def test_exact_canonical_hashes(self):
        catalog = json.loads((h.ROOT / "models/catalog.json").read_text(encoding="utf-8"))
        for name, expected in h.PINNED.items():
            self.assertEqual(h.sha256(h.ROOT / "models" / (name + ".yaml")), expected)
            self.assertEqual(next(e for e in catalog["detectors"] if e["id"] == name)["model_sha256"], expected)

    @unittest.skipUnless(importlib.util.find_spec("yaml"), "PyYAML absent; canonical parsing not tested")
    def test_real_yaml_inputs(self):
        for name, expected, bias in (("AK02", AK, 500), ("SAP22", SAP, 700)):
            doc, points = h.load_model(name)
            self.assertEqual(points, expected)
            self.assertEqual(doc["detectors"][0]["semiconductor"]["temperature"], 78)
            self.assertEqual(doc["detectors"][0]["contacts"][1]["potential"], bias)

    def test_order_and_gdml(self):
        for points in (AK, SAP):
            self.assertEqual(h.contour_from_document(document(points)), points)
            xml = ET.fromstring(h.gdml_text(points))
            actual = [(float(p.attrib["r"]), float(p.attrib["z"]))
                      for p in xml.findall("solids/genericPolycone/rzpoint")]
            self.assertEqual(actual, points[:-1])
            self.assertFalse(xml.findall("solids/polycone"))
            self.assertEqual(xml.find("structure/volume/solidref").attrib["ref"], "germanium_solid")
            self.assertEqual(len(xml.findall("structure/volume")), 2)

    def test_reject_unsupported_geometry(self):
        for change in (lambda d: d["units"].update(length="cm"),
                       lambda d: d["detectors"][0]["semiconductor"].update(material="Si"),
                       lambda d: d["detectors"][0]["semiconductor"]["geometry"].update(origin={"z": 1}),
                       lambda d: d["detectors"][0]["semiconductor"]["geometry"]["polycone"]["r"].pop(),
                       lambda d: d["detectors"][0]["semiconductor"]["geometry"]["polycone"]["r"].__setitem__(0, "0mm"),
                       lambda d: d["detectors"][0]["semiconductor"]["geometry"]["polycone"]["z"].__setitem__(0, float("nan"))):
            doc = document()
            change(doc)
            with self.subTest(doc=doc), self.assertRaises(ValueError):
                h.contour_from_document(doc)
        with self.assertRaises(ValueError):
            h.validate_contour(AK[:-1])
        with self.assertRaises(ValueError):
            h.load_model("../AK02")

    def test_analytic_box_cylinder_annulus_and_detector(self):
        rectangle = [(0, 0), (2, 0), (2, 3), (0, 3), (0, 0)]
        self.assertEqual(h.polygon_area(rectangle) * 4, 2 * 3 * 4)  # known extruded box
        self.assertAlmostEqual(h.revolved_volume(rectangle), math.pi * 2**2 * 3)
        annulus = [(1, 0), (2, 0), (2, 3), (1, 3), (1, 0)]
        self.assertAlmostEqual(h.revolved_volume(annulus), math.pi * (4 - 1) * 3)
        for name, points in (("AK02", AK), ("SAP22", SAP)):
            self.assertAlmostEqual(h.revolved_volume(points), h.reference_volume(name))

    def test_bore_groove_surface_and_axis(self):
        for points in (AK, SAP):
            probes = h.probe_points(points)
            self.assertTrue(any(p["expected"] == "surface" for p in probes))
            self.assertEqual(h.membership(points, [0, 0, 5]), "inside")
            self.assertEqual(h.membership(points, [1, 0, 1]), "outside")
            self.assertEqual(h.membership(points, [5, 0, 9]), "outside")
            radius = max(r for r, _ in points)
            self.assertEqual(h.membership(points, [radius + h.BOUNDARY_MM / 2, 0, 5]), "surface")
            self.assertEqual(h.membership(points, [radius + h.BOUNDARY_MM * 2, 0, 5]), "outside")

    def test_synthetic_transform_roundtrip(self):
        transform = copy.deepcopy(h.TRANSFORM)
        angle = .37
        transform["rotation_local_to_global"] = [[math.cos(angle), -math.sin(angle), 0],
                                                  [math.sin(angle), math.cos(angle), 0], [0, 0, 1]]
        transform["translation_global_mm"] = [12, -3, 17]
        points = np.array([[10, -2, 5], [-4, 8, 9]])
        np.testing.assert_allclose(h.to_local(h.to_global(points, transform), transform), points, atol=1e-12)
        for rotation in ([[1, 0, 0], [0, 1, 0], [0, 0, -1]],
                         [[1, .2, 0], [0, 1, 0], [0, 0, 1]], [[1, 0], [0, 1]],
                         [[float("nan"), 0, 0], [0, 1, 0], [0, 0, 1]]):
            transform["rotation_local_to_global"] = rotation
            with self.assertRaises(ValueError):
                h.validate_transform(transform)

    def test_macro_contract(self):
        macro = h.macro_text(AK, 100, 662)
        self.assertLess(macro.index("/run/initialize"), macro.index("/RMG/Output/Germanium/"))
        for command in ("StoreTrackID true", "StepPositionMode Both", "Cluster/PreClusterOutputs false",
                        "DiscardZeroEnergyHits false", "StoreSinglePrecisionEnergy false",
                        "StoreSinglePrecisionPosition false", "SkipPrimaryVertexOutput false"):
            self.assertIn(command, macro)
        self.assertNotIn("EdepCut", macro)
        self.assertIn("/gps/direction -1 0 0", macro)


class FixtureTests(unittest.TestCase):
    def setUp(self):
        scratch = h.local_path(h.ROOT / ".local/m2a/unit-tests")
        scratch.mkdir(parents=True, exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=scratch)
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.path = self.directory / "truth.lh5"
        fixture(self.path)
        self.meta = metadata()

    def test_flat_two_deposits_zero_event_and_delayed_event(self):
        before = h.sha256(self.path)
        result = h.extract_flat(self.path, self.meta)
        self.assertEqual([e["event_id"] for e in result["events"]], [0, 1, 2])
        self.assertEqual(result["events"][1]["steps"], [])
        self.assertEqual([s["energy_keV"] for s in result["events"][0]["steps"]], [1.25, 2.5, 0])
        self.assertEqual(result["events"][2]["primary_time_ns"], 40)
        self.assertEqual(result["events"][2]["steps"][0]["time_ns"], 1040)  # never +40
        self.assertEqual(result["energy_sum_keV"], 6.75)
        self.assertIn("unmapped_counter", result["source_fields"]["step_columns"])
        self.assertEqual(h.sha256(self.path), before)

    def test_all_no_hit_primaries(self):
        self.path.unlink()
        fixture(self.path, empty=True)
        result = h.extract_flat(self.path, self.meta)
        self.assertEqual(len(result["events"]), 3)
        self.assertTrue(all(not e["steps"] for e in result["events"]))

    def test_synthetic_rotated_fixture(self):
        transform = self.meta["coordinate_transform"]
        transform["rotation_local_to_global"] = [[0, -1, 0], [1, 0, 0], [0, 0, 1]]
        transform["translation_global_mm"] = [3, -8, 12]
        self.path.unlink()
        fixture(self.path, transform=transform)
        result = h.extract_flat(self.path, self.meta)
        np.testing.assert_allclose(result["events"][0]["steps"][0]["position_mm"], [10, 0, 5])

    def test_bad_flat_data_fails(self):
        cases = [
            ("foreign ID", lambda f: f[h.TABLE + "/evtid"].__setitem__(0, 9)),
            ("energy nan", lambda f: f[h.TABLE + "/edep"].__setitem__(0, np.nan)),
            ("negative energy", lambda f: f[h.TABLE + "/edep"].__setitem__(0, -1)),
            ("position inf", lambda f: f[h.TABLE + "/xloc"].__setitem__(0, np.inf)),
            ("time nan", lambda f: f[h.TABLE + "/time"].__setitem__(0, np.nan)),
            ("wrong units", lambda f: f[h.TABLE + "/xloc"].attrs.__setitem__("units", "mm")),
            ("energy units", lambda f: f[h.TABLE + "/edep"].attrs.__setitem__("units", "MeV")),
            ("vertex units", lambda f: f["vtx/time"].attrs.__setitem__("units", "s")),
            ("vertex duplicate", lambda f: f["vtx/evtid"].__setitem__(0, 0)),
            ("count mismatch", lambda f: f["number_of_simulated_events"].__setitem__((), 4)),
            ("absent census", lambda f: f.__delitem__("vtx")),
            ("outside", lambda f: f[h.TABLE + "/xloc"].__setitem__(0, .1)),
            ("outside endpoint", lambda f: f[h.TABLE + "/xloc_pre"].__setitem__(0, .1)),
            ("before vertex", lambda f: f[h.TABLE + "/time"].__setitem__(0, 20)),
            ("wrong multiplicity", lambda f: f["vtx/n_part"].__setitem__(0, 2)),
            ("reshaped t0", lambda f: f[h.TABLE].create_dataset("t0", data=[1., 2., 3., 4.])),
        ]
        for label, mutate in cases:
            path = self.directory / (label + ".lh5")
            fixture(path)
            with h5py.File(path, "r+") as f:
                mutate(f)
            with self.subTest(label=label), self.assertRaises(ValueError):
                h.extract_flat(path, self.meta)

    def test_noninteger_ids_lengths_and_reshaped(self):
        for name, replacement in (("evtid", np.array([2., 0., 0., .5])),
                                  ("trackid", np.array([1., 2., 2., 2.])),
                                  ("parent_trackid", np.array([0., 0., 1., 1.])),
                                  ("particle", np.array([22., 11., 11., 22.])),
                                  ("edep", np.array([1.])), ("edep", None)):
            path = self.directory / "bad.lh5"
            if path.exists():
                path.unlink()
            fixture(path)
            with h5py.File(path, "r+") as f:
                del f[h.TABLE + "/" + name]
                if replacement is None:
                    f.create_group(h.TABLE + "/" + name)
                else:
                    f[h.TABLE + "/" + name] = replacement
            with self.subTest(name=name), self.assertRaises(ValueError):
                h.extract_flat(path, self.meta)

    def test_duplicate_output_row_ids_rejected(self):
        result = h.extract_flat(self.path, self.meta)
        result["events"][0]["steps"][0]["raw_row_index"] = 0
        with self.assertRaisesRegex(ValueError, "duplicate"):
            h.validate_interchange(result)

    def test_boundary_tolerance_is_flagged_not_moved(self):
        original = (12.65 + h.BOUNDARY_MM / 2) / 1000
        with h5py.File(self.path, "r+") as f:
            f[h.TABLE + "/xloc"][0] = original
        result = h.extract_flat(self.path, self.meta)
        step = result["events"][2]["steps"][0]
        self.assertEqual(step["global_position_m"][0], original)
        self.assertGreater(step["position_mm"][0], 12.65)
        self.assertEqual(result["boundary"]["surface_rows"][0]["raw_row_index"], 0)

    def test_output_safety_and_immutable_inputs(self):
        with self.assertRaises(ValueError):
            h.local_path(h.ROOT / "transport/new-output")
        with self.assertRaises(ValueError):
            h.local_path(h.ROOT / ".local/../transport/new-output")
        with self.assertRaises(ValueError):
            h.prepare("AK02", self.directory)
        target = self.directory / "prepared"
        with patch.object(h, "load_model", return_value=(document(), AK)):
            h.prepare("AK02", target)
            h.read_prepared(target)
            (target / "run.mac").write_text("changed", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "immutable"):
                h.read_prepared(target)

    def test_symlink_escape(self):
        link = self.directory / "linked"
        try:
            link.symlink_to(h.ROOT / "transport", target_is_directory=True)
        except OSError as error:
            self.skipTest("symlinks unavailable: " + str(error))
        with self.assertRaises(ValueError):
            h.local_path(link / "escaped")

    def test_no_partial_final_json(self):
        final = self.directory / "events.json"
        with self.assertRaises(ValueError):
            h.publish_json(final, {"bad": float("nan")})
        self.assertFalse(final.exists())
        with patch.object(h.os, "link", side_effect=OSError("simulated publication failure")):
            with self.assertRaises(OSError):
                h.publish_json(final, {"valid": True})
        self.assertFalse(final.exists())
        self.assertTrue((self.directory / "events.json.partial").exists())
        other = self.directory / "complete.json"
        h.publish_json(other, {"valid": True})
        before = other.read_bytes()
        with self.assertRaises(ValueError):
            h.publish_json(other, {"overwrite": True})
        self.assertEqual(other.read_bytes(), before)

    def test_extraction_rejects_before_writing(self):
        (self.directory / "prepared.json").write_text("{}", encoding="utf-8")
        with h5py.File(self.path, "r+") as f:
            f[h.TABLE + "/edep"][0] = -1
        status = {"status": "complete", "prepared_sha256": h.sha256(self.directory / "prepared.json"),
                  "source_lh5_sha256": h.sha256(self.path), "versions": {"test": "synthetic"}}
        h.publish_json(self.directory / "run.json", status)
        with patch.object(h, "read_prepared", return_value=(self.directory, self.meta)):
            with self.assertRaises(ValueError):
                h.extract(self.directory)
        self.assertFalse((self.directory / "events.json").exists())
        self.assertFalse((self.directory / "events.json.partial").exists())

    def test_run_failure_evidence_and_no_rerun(self):
        target = self.directory / "failed-run"
        with patch.object(h, "load_model", return_value=(document(), AK)):
            h.prepare("AK02", target)
            with patch.object(h.subprocess, "run", side_effect=OSError("simulated missing executable")):
                with self.assertRaises(OSError):
                    h.run(target)
            self.assertEqual(json.loads((target / "run.json").read_text())["status"], "failed")
            self.assertIn("simulated missing executable", (target / "run.log").read_text())
            with self.assertRaisesRegex(ValueError, "fresh"):
                h.run(target)

    def test_mocked_run_and_extract_pipeline(self):
        target = self.directory / "mocked-run"

        def fake_process(command, *, cwd, **kwargs):
            self.assertEqual(cwd, target)
            self.assertNotIn("shell", kwargs)
            if "--version" in command:
                return CompletedProcess(command, 0, stdout="synthetic-test-version\n")
            self.assertEqual(command, ["remage", "--flat-output", "-t", "1", "--rand-seed", "260925",
                                       "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"])
            fixture(cwd / "truth.lh5")
            return CompletedProcess(command, 0)

        with patch.object(h, "load_model", return_value=(document(), AK)):
            h.prepare("AK02", target, events=3)
            with patch.object(h.subprocess, "run", side_effect=fake_process):
                status = h.run(target)
            self.assertEqual(status["status"], "complete")
            output = h.extract(target)
            result = json.loads(output.read_text())
            self.assertEqual(result["primary_count"], 3)
            self.assertEqual(result["energy_sum_keV"], 6.75)
            self.assertEqual(result["provenance"]["versions"]["remage"], "synthetic-test-version")
            with self.assertRaisesRegex(ValueError, "already exists"):
                h.extract(target)

    def test_primary_kinematics_and_event_energy(self):
        changes = [
            lambda f: f["particles/particle"].__setitem__(0, 11),
            lambda f: f["particles/ekin"].__setitem__(0, .663),
            lambda f: f["particles/px"].__setitem__(0, -.5),
            lambda f: f.__delitem__("particles"),
            lambda f: f["particles/evtid"].__setitem__(0, 0),
            lambda f: f[h.TABLE + "/edep"].__setitem__(0, 663.),
        ]
        for change in changes:
            fixture(self.path)
            with h5py.File(self.path, "r+") as f:
                change(f)
            with self.assertRaises(ValueError):
                h.extract_flat(self.path, self.meta)

    def test_zero_exit_with_macro_error_is_failed(self):
        target = self.directory / "macro-error"

        def fake_process(command, *, cwd, **kwargs):
            if "--version" in command:
                return CompletedProcess(command, 0, stdout="synthetic-test-version\n")
            kwargs["stdout"].write("***** COMMAND NOT FOUND </RMG/Output/Unknown> *****\n")
            return CompletedProcess(command, 0)

        with patch.object(h, "load_model", return_value=(document(), AK)):
            h.prepare("AK02", target, events=3)
            with patch.object(h.subprocess, "run", side_effect=fake_process):
                with self.assertRaisesRegex(ValueError, "diagnostic"):
                    h.run(target)
            self.assertEqual(json.loads((target / "run.json").read_text())["status"], "failed")


if __name__ == "__main__":
    unittest.main(verbosity=2)
