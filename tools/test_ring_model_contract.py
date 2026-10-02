"""Focused model-delta, slanted-contour and unchanged event-contract checks."""
import copy
import json
import math
from pathlib import Path
import sys
import unittest

CHECK_NATIVE = "--native" in sys.argv
if CHECK_NATIVE:
    sys.argv.remove("--native")

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"transport"))
import cs137
import handoff
import ring_cs137 as ring
import ring_model_contract as models
import test_cs137 as raw_fixtures


class RingContracts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.output=ROOT/".local/ring-delivery-v1/model-contract-tests"
        cls.output.mkdir(parents=True,exist_ok=True)

    def artifact(self,name,body):
        path=self.output/name
        if path.exists():
            self.assertEqual(path.read_bytes(),body,"saved test evidence changed")
        else:
            with path.open("xb") as stream:
                stream.write(body)
        return path.relative_to(ROOT).as_posix()

    def test_exact_50min_bytes_and_unchanged_geometry(self):
        original,parsed,body,_=models.inputs("GeRC02")
        self.assertEqual(body,(ROOT/"models/GeRC02.yaml").read_bytes().replace(models.DELTA_FROM,models.DELTA_TO,1))
        self.assertEqual(original["detectors"][0]["semiconductor"]["geometry"],parsed["detectors"][0]["semiconductor"]["geometry"])
        ref=self.artifact("GeRC02-valid.yaml",body)
        self.assertEqual(models.validate(models.contract("GeRC02",ref))["annealing_time_minutes"],50)

    def test_rehashed_unauthorized_change_is_refused(self):
        _,_,body,_=models.inputs("GeRC02")
        body=body.replace(b"potential: 240",b"potential: 241",1)
        ref=self.artifact("GeRC02-rehashed-invalid-bias.yaml",body)
        value=models.contract("GeRC02",ref)
        value["effective_model_sha256"]=models.digest(body)
        with self.assertRaises(ValueError): models.validate(value)

    def test_rehashed_original_time_is_refused(self):
        body=(ROOT/"models/GeRC02.yaml").read_bytes()
        ref=self.artifact("GeRC02-rehashed-invalid-30min.yaml",body)
        value=models.contract("GeRC02",ref)
        value["effective_model_sha256"]=models.digest(body)
        value["annealing_time_minutes"]=30
        with self.assertRaises(ValueError): models.validate(value)

    def test_km_original_and_dependency_identity(self):
        value=models.contract("KMRC01_candidate","models/KMRC01_candidate.yaml")
        self.assertEqual(value["source_model_sha256"],value["effective_model_sha256"])
        self.assertIsNone(value["model_delta"])
        self.assertEqual(set(value["dependencies_sha256"]),{"models/ADLChargeDriftModel/drift_velocity_config.yaml"})
        models.validate(value)

    def test_independent_ring_volumes_and_bore_membership(self):
        for model,count in (("GeRC02",32),("KMRC01_candidate",56)):
            points=ring.contour(model)
            self.assertTrue(math.isclose(handoff.revolved_volume(points),ring.reference_volume(model),rel_tol=1e-12))
            self.assertEqual(len(ring.probes(model,points)),count)
            self.assertEqual(handoff.membership(points,[0,0,5]),"outside")
            self.assertEqual(handoff.membership(points,[10,0,5]),"inside")

    def test_slant_midpoint_offsets_are_geometric(self):
        for model in ring.MODELS:
            points=ring.contour(model)
            slants=[(a,b) for a,b in zip(points,points[1:]) if a[0] != b[0] and a[1] != b[1]]
            self.assertEqual(len(slants),2)
            for a,b in slants:
                mid=[(a[0]+b[0])/2,0,(a[1]+b[1])/2]
                self.assertEqual(handoff.membership(points,mid),"surface")
                self.assertEqual(handoff.membership(points,[mid[0]-1e-4,0,mid[2]]),"inside")
                self.assertEqual(handoff.membership(points,[mid[0]+1e-4,0,mid[2]]),"outside")

    def test_slanted_self_intersection_rejected_and_legacy_stays_strict(self):
        with self.assertRaises(ValueError): ring.validate_contour([(1,0),(3,2),(1,2),(3,0),(1,0)])
        with self.assertRaises(ValueError): handoff.validate_contour(ring.contour("GeRC02"))
        for model in handoff.PINNED:
            handoff.load_model(model)

    def test_synthetic_raw_ledger_preserves_zeros_delays_and_ancestry_in_rings(self):
        raw=self.output/"synthetic-delayed-ledger.lh5"
        if not raw.exists():
            raw_fixtures.fixture(raw)
        for model in ring.MODELS:
            meta={"primary_count":3,"coordinate_transform":handoff.TRANSFORM,
                  "contour_rz_mm":ring.contour(model),"material_tables":{"stp/germanium":"G4_Ge"},
                  "grouping_policy":cs137.POLICY}
            rows=list(cs137.iter_decays(raw,meta))
            self.assertEqual([e["event_id"] for e in rows],[0,1,2])
            self.assertEqual([len(e["steps"]) for e in rows],[3,0,0])
            self.assertEqual([e["line_photon_count"] for e in rows],[1,1,1])
            self.assertEqual(rows[0]["steps"][0]["energy_keV"],0)
            self.assertEqual(rows[0]["steps"][2]["time_ns"],120000100001.)
            self.assertEqual(rows[0]["pulse_groups"][1]["row_indices"],[2])
            self.assertEqual(rows[2]["tracks"][2]["parent_trackid"],2)

    def test_nominal_mount_roundtrip_and_event_window_preserved(self):
        value=ring.scenario(); transform=value["coordinate_transform"]
        for xyz in ([10,0,5],[11.98,0,10.25],[0,0,0]):
            handoff.np.testing.assert_allclose(handoff.to_local(handoff.to_global(xyz,transform),transform),xyz,atol=1e-12,rtol=0)
        self.assertEqual(value["source"]["position_global_mm"],[0,37.073,0.290])
        self.assertEqual(value["spacer"],cs137.load(ROOT/"transport/cryostat_nominal.json")["spacer"])
        steps=[{"raw_row_index":i,"energy_keV":e,"time_ns":t} for i,(e,t) in enumerate([(0,0),(1,0),(2,99999),(3,100000),(4,199999),(5,200000)])]
        groups=cs137.group_deposits(steps)
        self.assertEqual([g["row_indices"] for g in groups],[[1,2],[3,4],[5]])
        self.assertTrue(groups[1]["boundary_split_within_horizon"])
        self.assertEqual(sum(len(g["row_indices"]) for g in groups),5)

    @unittest.skipUnless(CHECK_NATIVE,"use --native after the geometry-only preparations")
    def test_saved_native_preparations_are_complete_and_source_bound(self):
        for model,leaf in (("GeRC02","geometry-GeRC02-corrected"),("KMRC01_candidate","geometry-KMRC01_candidate")):
            directory,meta=ring.read_prepared(ROOT/".local/ring-delivery-v1"/leaf)
            receipt=cs137.load(directory/"prepare-receipt.json")
            report=cs137.load(directory/"geometry-report.json")
            self.assertEqual(receipt["status"],"complete")
            self.assertEqual(receipt["returncode"],0)
            self.assertEqual(meta["model_id"],model)
            self.assertEqual(meta["model_sha256"],models.PINS[model])
            self.assertEqual(meta["source_sha256"],cs137.source_hashes())
            self.assertTrue(report["overlaps_passed"])
            self.assertFalse((directory/"truth.lh5").exists(),"geometry check must not launch radiation")


if __name__ == "__main__":
    unittest.main(verbosity=2)
