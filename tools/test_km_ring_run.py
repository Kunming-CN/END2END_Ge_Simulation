"""Bounded admission/retention checks only; no Geant4, Julia or SSD invocation."""
import copy
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import km_ring_run as k
import ring_run as r

EVIDENCE = r.ROOT / ".local/ring-delivery-v1/km-runner-tests-v1"


class KMRunnerTests(unittest.TestCase):
    def test_rehashed_gain_edit_cannot_change_resolved_profile(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        path = EVIDENCE / "readout-config.json"
        expected = r.expected_readout(500)
        edited = copy.deepcopy(expected); edited["gain"] *= 2
        path.write_text(json.dumps(edited) + "\n", encoding="utf-8")
        report = {"config_sha256": r.sha(path)}
        with self.assertRaisesRegex(ValueError, "even if rehashed"):
            k.check_readout_config(EVIDENCE, report, 500)
        path.write_text(json.dumps(expected) + "\n", encoding="utf-8")
        self.assertEqual(k.check_readout_config(EVIDENCE, {"config_sha256": r.sha(path)}, 500), expected)

    def test_only_primary_count_changes_between_pilot_and_production(self):
        p = r.expected_readout(500); q = r.expected_readout(10000)
        self.assertEqual({name: value for name, value in p.items() if name != "expected_primary_count"},
                         {name: value for name, value in q.items() if name != "expected_primary_count"})

    def test_identity_rejects_boolean_and_fractional_aliases(self):
        for value in (True, False, 0.0, -1, "0"):
            with self.assertRaises(ValueError):
                k.census_id(value)
        self.assertEqual(k.census_id(0), 0)

    def test_existing_native_command_remains_negative_and_requests_all_samples(self):
        c = {"julia_threads": 2}; modeldir = k.CAMPAIGN / "production10000" / k.MODEL
        command = k.response_command(c, modeldir)
        self.assertEqual(command[command.index("--charge-csv") + 1], "all")
        self.assertEqual(command[command.index("--native-failure-policy") + 1], "record")
        self.assertEqual(command[5], "simulation/ring_response.jl")
        self.assertNotIn("simulation/ring_polarity.jl", command)

    def test_completed_receipt_is_checked_before_worker_admission(self):
        terminal = k.CAMPAIGN / "km-pilot-COMPLETE.json"
        native_exists = Path.exists
        with (patch.object(k, "configuration", return_value={}),
              patch.object(k, "verify", return_value={"status": "completed"}) as verify,
              patch.object(k, "idle", side_effect=AssertionError("must not launch"))):
            with patch.object(Path, "exists", lambda path: path == terminal or native_exists(path)):
                self.assertEqual(k.run(k.CAMPAIGN), {"status": "completed"})
        verify.assert_called_once_with(k.CAMPAIGN, "pilot")

    def test_native_failure_nulls_and_zero_records_remain_exact(self):
        modeldir = EVIDENCE / "test-only-failure-retention"
        response = modeldir / "response"; output = modeldir / k.DERIVATIVE
        response.mkdir(parents=True, exist_ok=True); output.mkdir(exist_ok=True)
        zero = {"record_kind": "decay", "event_id": 0, "global_decay_id": 0,
                "group_id": None, "zero_deposit": True, "test_only": True}
        failure = {"record_kind": "pulse", "event_id": 1, "global_decay_id": 1, "group_id": 0,
                   "status": "native_transport_failed", "native_error": {"message": "Invalid waveform support"},
                   "readout": None, "final_induced_keV": None, "transport_flags": None, "accepted": False,
                   "test_only": True}
        raw = [zero, failure]
        (response / "scalars.jsonl").write_text("".join(json.dumps(row) + "\n" for row in raw), encoding="utf-8")
        (response / "signals.csv").write_text(",".join(k.SIGNAL_HEADER) + "\n", encoding="utf-8")
        (output / "scalars.jsonl").write_text("".join(json.dumps(row) + "\n" for row in raw), encoding="utf-8")
        (output / "traces.jsonl").write_text("", encoding="utf-8")
        (output / "readout-input.csv").write_text(",".join(k.INPUT_HEADER) + "\n", encoding="utf-8")
        counts = {"accepted": 0, "rejected": 1, "readout_rejected": 0, "saturated": 0,
                  "analog_samples": 0, "native_charge_samples": 0, "native_failed_groups": 1}
        k.derivative_ledger(modeldir, {"counts": counts}, {"counts": counts, "ionisation_energy_eV": 2.95})
        edited = copy.deepcopy(raw); edited[1]["final_induced_keV"] = 0.0
        (output / "scalars.jsonl").write_text("".join(json.dumps(row) + "\n" for row in edited), encoding="utf-8")
        with self.assertRaisesRegex(ValueError, "native-failure records"):
            k.derivative_ledger(modeldir, {"counts": counts}, {"counts": counts, "ionisation_energy_eV": 2.95})


if __name__ == "__main__":
    unittest.main()
