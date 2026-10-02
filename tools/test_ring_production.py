"""Read-only saved-pilot admission checks; never launch a worker or simulation."""
import copy
import unittest
import ring_production as p


class AdmissionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = p.r.ROOT / ".local/ring-cs137-v1"
        cls.modeldir = cls.directory / "pilot500/GeRC02"
        cls.config = p.r.config(cls.directory)
        cls.records = [p.r.read(cls.directory / "stages" / ("pilot500-GeRC02-" + s + ".json"))
                       for s in ("prepare", "transport", "extract", "response")]

    def test_actual_pilot_provenance(self):
        result = p.verify(self.directory, "GeRC02")
        self.assertEqual(result["result"]["counts"]["initial_primaries"], 500)
        self.assertEqual(result["result"]["counts"]["native_failed_groups"], 0)

    def test_explicit_synthetic_fixture_rejected(self):
        fixture = p.r.ROOT / ".local/ring-delivery-v1/runner-tests-v1/synthetic-terminal-fixture"
        with self.assertRaisesRegex(ValueError, "Test-only"):
            p.science_artifacts(fixture)

    def test_rehashed_command_change_rejected(self):
        records = copy.deepcopy(self.records); records[0]["command_argv"][-1] = "26100299"
        with self.assertRaisesRegex(ValueError, "mismatch"):
            p.stages(self.config, self.modeldir, records)

    def test_changed_source_or_supervisor_rejected(self):
        records = copy.deepcopy(self.records); records[0]["source_sha256"]["tools/ring_run.py"] = "0" * 64
        with self.assertRaisesRegex(ValueError, "mismatch"):
            p.stages(self.config, self.modeldir, records)
        records = copy.deepcopy(self.records); records[-1]["supervisor_pid"] += 1
        with self.assertRaisesRegex(ValueError, "supervisor"):
            p.stages(self.config, self.modeldir, records)

    def test_km_unaccepted_pilot_refused(self):
        with self.assertRaisesRegex(ValueError, "Pilot cannot promote"):
            p.verify(self.directory, "KMRC01_candidate")

    def test_wrong_launcher_phase_or_campaign_rejected(self):
        launch = p.r.read(self.directory / "pilot-both-launcher.json")
        p.launcher_intent(self.config, self.directory, "GeRC02", "both", launch)
        launch["command_argv"][-3] = "production"
        with self.assertRaisesRegex(ValueError, "intent"):
            p.launcher_intent(self.config, self.directory, "GeRC02", "both", launch)
        launch = p.r.read(self.directory / "pilot-both-launcher.json"); launch["output_root"] += "-other"
        with self.assertRaisesRegex(ValueError, "intent"):
            p.launcher_intent(self.config, self.directory, "GeRC02", "both", launch)


if __name__ == "__main__":
    unittest.main(verbosity=2)
