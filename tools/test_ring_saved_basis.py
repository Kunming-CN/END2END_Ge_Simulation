"""Synthetic boundary cases plus optional real, read-only completed-data checks.

Synthetic manifests are explicitly enrolled only inside test patches. They never
serve the production API. No test launches a simulator or edits campaign science.
"""
from contextlib import ExitStack
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import ring_saved_basis as saved

EVIDENCE = saved._ROOT / ".local/ring-delivery-v1/portable-helper"


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n", encoding="utf-8")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class SyntheticBoundary(unittest.TestCase):
    def setUp(self):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        self.root = Path(tempfile.mkdtemp(prefix="boundary-", dir=EVIDENCE)).resolve()
        self.directory = self.root / saved._CAMPAIGN
        self.archive = self.directory / "source-basis-v1/ring_run.py"
        original = b'from pathlib import Path\nJULIA = Path("fixture-runtime")\n# synthetic only\n'
        self.archive.parent.mkdir(parents=True)
        self.archive.write_bytes(original)
        control = self.root / "tools/ring_run.py"
        control.parent.mkdir(parents=True)
        control.write_bytes(original)
        source44 = {"tools/ring_run.py": digest(control)}
        for number in range(43):
            name = "sources/base-" + str(number) + ".txt"
            path = self.root / name
            path.parent.mkdir(exist_ok=True)
            path.write_text("synthetic-" + str(number), encoding="utf-8")
            source44[name] = digest(path)
        source51 = source44.copy()
        for number in range(7):
            name = "sources/extra-" + str(number) + ".txt"
            path = self.root / name
            path.write_text("extra-" + str(number), encoding="utf-8")
            source51[name] = digest(path)
        for name in ("ring_saved_basis.py", "km_ring_run.py", "ring_production.py"):
            (self.root / "tools" / name).write_text("# synthetic verifier hash only\n", encoding="utf-8")
        self.receipts = {
            "config.json": {"source_sha256": source44, "julia_executable": str(self.root / "runtime/julia.exe")},
            "km-config.json": {"source_sha256": source51},
            "production-GeRC02-COMPLETE.json": {"status": "completed", "test_only": False},
            "km-pilot-COMPLETE.json": {"status": "completed", "test_only": False},
            "km-production-COMPLETE.json": {"status": "completed", "test_only": False},
            "fixture-supervisor-exit.json": {"unresolved_child_intent": False},
        }
        for number in range(25):
            self.receipts["stages/fixture-" + str(number) + ".json"] = {"test_only": True, "fixture": number}
        for name, value in self.receipts.items():
            write(self.directory / name, value)
        for name in ("config", "km-config"):
            (self.directory / (name + ".sha256")).write_text(digest(self.directory / (name + ".json")) + "\n", encoding="ascii")
        self.basis = {"kind": "completed_ring_source_basis_v1", "root": str(self.root),
                      "supervisor_python": str(self.root / "runtime/python.exe"),
                      "original_all44": source44, "original_all51": source51,
                      "archived_sources": {"tools/ring_run.py": {"archive": "ring_run.py", "bytes": len(original),
                                                                 "sha256": digest(self.archive)}},
                      "receipt_sha256": {name: digest(self.directory / name) for name in self.receipts}}
        self.basis_path = self.root / saved._BASIS
        write(self.basis_path, self.basis)
        self.patches = ExitStack()
        self.patches.enter_context(patch.object(saved, "_ROOT", self.root))
        self.patches.enter_context(patch.object(saved, "_BASIS_SHA", digest(self.basis_path)))

    def tearDown(self):
        self.patches.close()
        target = self.root.resolve()
        self.assertTrue(target.is_relative_to(EVIDENCE.resolve()) and target != EVIDENCE.resolve())
        shutil.rmtree(target)

    def reseal_test_basis(self):
        """Enroll synthetic semantics for a specific negative test, never real data."""
        write(self.basis_path, self.basis)
        saved._BASIS_SHA = digest(self.basis_path)

    def modules(self, verifier):
        runner = SimpleNamespace(ROOT=self.root, JULIA=Path("current-runtime"), sha=saved._digest,
                                 atomic=lambda *a, **k: None, prepare=lambda *a, **k: None,
                                 run=lambda *a, **k: None, start=lambda *a, **k: None,
                                 execute=lambda *a, **k: None, model_pipeline=lambda *a, **k: None,
                                 main=lambda *a, **k: None)
        provenance = SimpleNamespace(r=runner, start=lambda *a, **k: None)
        km = SimpleNamespace(r=runner, provenance=provenance, CAMPAIGN=self.directory,
                             verify=verifier, prepare=lambda *a, **k: None, run=lambda *a, **k: None,
                             start=lambda *a, **k: None, execute=lambda *a, **k: None, main=lambda *a, **k: None)
        return runner, km, provenance, None

    def test_original_and_only_portable_line_are_accepted(self):
        saved._load_basis()
        original = self.archive.read_bytes()
        old_line = next(x for x in original.splitlines(keepends=True) if x.startswith(b"JULIA = "))
        (self.root / "tools/ring_run.py").write_bytes(original.replace(old_line, saved._PORTABLE_LINE + b"\n"))
        saved._load_basis()

    def test_rehashed_config_is_rejected(self):
        path = self.directory / "config.json"
        value = copy.deepcopy(self.receipts["config.json"])
        value["julia_executable"] = "retargeted-runtime"
        write(path, value)
        path.with_suffix(".sha256").write_text(digest(path) + "\n", encoding="ascii")
        with self.assertRaisesRegex(ValueError, "Historical receipt changed"):
            saved._load_basis()

    def test_rehashed_terminal_is_rejected(self):
        path = self.directory / "km-production-COMPLETE.json"
        write(path, {"status": "completed", "test_only": False, "changed_result": True})
        path.with_suffix(".sha256").write_text(digest(path), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "Historical receipt changed"):
            saved._load_basis()

    def test_other_source_and_unapproved_control_edits_are_rejected(self):
        for name in ("sources/base-0.txt", "tools/ring_run.py"):
            with self.subTest(name=name):
                path = self.root / name
                original = path.read_bytes()
                path.write_bytes(original + b"\nchanged\n")
                with self.assertRaisesRegex(ValueError, "source|control-source"):
                    saved._load_basis()
                path.write_bytes(original)

    def test_changed_archive_is_rejected(self):
        self.archive.write_bytes(self.archive.read_bytes() + b"changed")
        with self.assertRaisesRegex(ValueError, "archive bytes changed"):
            saved._load_basis()

    def test_rehashed_basis_and_unknown_archive_are_rejected(self):
        self.basis["archived_sources"]["unknown.py"] = self.basis["archived_sources"]["tools/ring_run.py"].copy()
        write(self.basis_path, self.basis)
        self.basis_path.with_suffix(".sha256").write_text(digest(self.basis_path), encoding="ascii")
        with self.assertRaisesRegex(ValueError, "Unregistered or changed"):
            saved._load_basis()
        self.reseal_test_basis()
        with self.assertRaisesRegex(ValueError, "Unknown archived"):
            saved._load_basis()

    def test_unknown_model_is_rejected_before_loading(self):
        with patch.object(saved, "_load_basis", side_effect=AssertionError("must not load")):
            with self.assertRaisesRegex(ValueError, "Unknown completed"):
                saved.verify("both")

    def test_unknown_root_is_rejected(self):
        self.basis["root"] = str(self.root.parent)
        self.reseal_test_basis()
        with self.assertRaisesRegex(ValueError, "root differs"):
            saved._load_basis()

    def test_lock_is_rejected(self):
        (self.directory / ".supervisor.lock").mkdir()
        with self.assertRaisesRegex(ValueError, "lock"):
            saved._load_basis()

    def test_nonterminal_and_unresolved_child_are_rejected(self):
        for name, value in (("km-production-COMPLETE.json", {"status": "running"}),
                            ("fixture-supervisor-exit.json", {"unresolved_child_intent": True})):
            with self.subTest(name=name):
                original = (self.directory / name).read_bytes()
                old_pin = self.basis["receipt_sha256"][name]
                write(self.directory / name, value)
                self.basis["receipt_sha256"][name] = digest(self.directory / name)
                self.reseal_test_basis()
                with self.assertRaisesRegex(ValueError, "completed real terminal|unresolved child"):
                    saved._load_basis()
                (self.directory / name).write_bytes(original)
                self.basis["receipt_sha256"][name] = old_pin
                self.reseal_test_basis()

    def test_guard_blocks_mutators_writers_and_processes_then_restores(self):
        modules = self.modules(None)
        runner, km, provenance, _ = modules
        original_sha, original_julia, original_run = runner.sha, runner.JULIA, subprocess.run
        untouched = self.directory / "must-not-exist.json"
        operations = [lambda: runner.prepare(self.directory), lambda: runner.run(self.directory),
                      lambda: runner.start(self.directory), lambda: runner.execute(self.directory),
                      lambda: runner.atomic(untouched, {}), lambda: km.prepare(self.directory),
                      lambda: km.run(self.directory), lambda: km.start(self.directory),
                      lambda: km.execute(self.directory), lambda: provenance.start(self.directory),
                      lambda: subprocess.Popen(["forbidden"]), lambda: subprocess.run(["forbidden"]),
                      lambda: untouched.write_text("forbidden"), lambda: untouched.open("wb"),
                      lambda: open(untouched, "w"), lambda: os.open(untouched, os.O_CREAT | os.O_WRONLY)]

        def verifier(*args, **kwargs):
            for operation in operations:
                with self.assertRaisesRegex(ValueError, "cannot"):
                    operation()
            self.assertEqual(runner.sha(self.root / "tools/ring_run.py"), digest(self.archive))
            self.assertEqual(runner.sha(self.root / "sources/base-0.txt"), digest(self.root / "sources/base-0.txt"))
            return {"status": "completed", "result": {"test_only": True}, "new_science_stages": 0}

        km.verify = verifier
        with patch.object(saved, "_modules", return_value=modules):
            result = saved.verify("KMRC01_candidate")
        self.assertEqual(result["verification_basis"], "recorded_sources_v1")
        self.assertEqual(result["new_science_stages"], 0)
        self.assertIs(runner.sha, original_sha)
        self.assertEqual(runner.JULIA, original_julia)
        self.assertIs(subprocess.run, original_run)
        self.assertFalse(untouched.exists())

    def test_guard_restores_after_failure_and_denies_nested_operation(self):
        def verifier(*args, **kwargs):
            with self.assertRaisesRegex(ValueError, "already active"):
                saved.verify("KMRC01_candidate")
            raise RuntimeError("synthetic verifier failure")
        modules = self.modules(verifier)
        original_sha = modules[0].sha
        with patch.object(saved, "_modules", return_value=modules):
            with self.assertRaisesRegex(RuntimeError, "synthetic verifier failure"):
                saved.verify("KMRC01_candidate")
        self.assertIs(modules[0].sha, original_sha)
        self.assertFalse(saved._SERIAL.locked())

    def test_publication_operation_is_closed_and_only_calls_checked_inputs(self):
        modules = self.modules(lambda *a, **k: self.fail("KM verifier is not the publication entry"))
        seen = []
        exporter = SimpleNamespace(_checked_inputs=lambda model: seen.append(model) or {"model": model},
                                   build=lambda: self.fail("build must never be called"))
        with patch.object(saved, "_modules", return_value=(*modules[:3], exporter)):
            self.assertEqual(saved.publication_inputs("GeRC02"), {"model": "GeRC02"})
        self.assertEqual(seen, ["GeRC02"])


@unittest.skipUnless((saved._ROOT / saved._BASIS).is_file(), "Registered local completed science is unavailable")
class RealCompletedReadOnly(unittest.TestCase):
    def test_real_completed_campaign_and_exact_receipts_are_unchanged(self):
        basis, directory, _, _ = saved._load_basis()
        before = {name: digest(directory / name) for name in basis["receipt_sha256"]}
        for model, expected in (("GeRC02", (297, 231, 4, 9703)),
                                ("KMRC01_candidate", (231, 230, 0, 9769))):
            with self.subTest(model=model):
                result = saved.verify(model)
                counts = result["result"]["counts"]
                self.assertEqual(counts["initial_primaries"], 10000)
                self.assertEqual(tuple(counts[key] for key in ("groups", "accepted", "native_failed_groups",
                                                               "zero_deposit_primaries")), expected)
                self.assertEqual(result["new_science_stages"], 0)
                self.assertEqual(result["basis_sha256"], saved._BASIS_SHA)
        self.assertEqual(before, {name: digest(directory / name) for name in before})


if __name__ == "__main__":
    unittest.main()
