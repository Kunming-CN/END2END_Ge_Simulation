"""Adverse fixtures for source-input verification; no scientific execution."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import shutil
import stat
import tempfile
import unittest
from unittest.mock import patch

import check_cryostat_inputs as c

EVIDENCE = c.ROOT / ".local/m11e-cryostat-inputs-v1"


class CryostatInputsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        EVIDENCE.mkdir(parents=True, exist_ok=True)
        cls.ledger = c.parse_json((c.ROOT / c.LEDGER_REF).read_bytes())
        cls.manifest = c.parse_json((c.ROOT / c.MANIFEST_REF).read_bytes())
        cls.local_available = all((c.ROOT / ".local/transport/LBNL" / r["file"]).is_file()
                                  for r in cls.ledger["inventory"])

    def fixture(self, originals=False):
        if originals and not self.local_available:
            self.skipTest("explicit local cases need the nine pinned private originals")
        directory = tempfile.TemporaryDirectory(prefix="fixture-", dir=EVIDENCE)
        self.addCleanup(directory.cleanup)
        root = Path(directory.name)
        (root / "transport").mkdir()
        for ref in (c.LEDGER_REF, c.MANIFEST_REF):
            shutil.copyfile(c.ROOT / ref, root / ref)
        if originals:
            cache = root / ".local/transport/LBNL"
            cache.mkdir(parents=True)
            for row in self.ledger["inventory"]:
                shutil.copyfile(c.ROOT / ".local/transport/LBNL" / row["file"], cache / row["file"])
        return root

    def changed(self, section, key, value):
        ledger = copy.deepcopy(self.ledger)
        ledger[section][key] = value
        return ledger

    def rejects(self, ledger, pattern):
        with self.assertRaisesRegex(c.InputError, pattern):
            c.validate_ledger(ledger, self.manifest)

    def texts(self):
        if not self.local_available:
            self.skipTest("selected lexical cases need the nine pinned private originals")
        return {r["file"]: (c.ROOT / ".local/transport/LBNL" / r["file"]).read_text(encoding="utf-8")
                for r in self.ledger["inventory"]}

    def test_portable_clone_needs_no_private_inputs(self):
        root = self.fixture()
        calls = []
        original = c.read_bounded
        def record(project, ref, limit):
            self.assertFalse(ref.startswith(".local/"))
            calls.append(ref)
            return original(project, ref, limit)
        with patch.object(c, "read_bounded", side_effect=record):
            result = c.check(root)
        self.assertEqual(calls, [c.MANIFEST_REF, c.LEDGER_REF])
        self.assertEqual(result["local_source_files_read"], 0)
        self.assertEqual(result["native_geometry_acceptance"], "not_run")

    def test_local_existing_nine_originals(self):
        result = c.check(self.fixture(originals=True), check_local=True)
        self.assertEqual(result["local_source_files_read"], 9)
        self.assertEqual(result["experimental_geometry_acceptance"], "not_established")

    def test_missing_private_input_is_only_explicit_local_failure(self):
        root = self.fixture()
        self.assertEqual(c.check(root)["status"], "passed")
        with self.assertRaises(FileNotFoundError):
            c.check(root, check_local=True)

    def test_duplicate_json_keys_and_nonfinite_numbers(self):
        for data in (b'{"a":1,"a":2}', b'{"x":NaN}', b'{"x":Infinity}', b'{"x":-Infinity}', b'{"x":1e999}'):
            with self.subTest(data=data), self.assertRaises(c.InputError):
                c.parse_json(data)

    def test_invalid_json_encoding_and_syntax(self):
        for data in (b'\xff', b'{', b'{"x":}'):
            with self.subTest(data=data), self.assertRaises(c.InputError):
                c.parse_json(data)

    def test_types_cannot_alias_valid_values(self):
        ledger = copy.deepcopy(self.ledger)
        ledger["schema_version"] = True
        self.rejects(ledger, "schema version")
        ledger = copy.deepcopy(self.ledger)
        ledger["inventory"][0]["bytes"] = True
        self.rejects(ledger, "type")
        ledger = copy.deepcopy(self.ledger)
        ledger["current_adapter"]["native_expected_volume_count"] = 20.0
        self.rejects(ledger, "adapter boundary")

    def test_duplicate_inventory_variant_and_placement(self):
        for key in ("inventory", "variants", "placements"):
            ledger = copy.deepcopy(self.ledger)
            ledger[key].append(copy.deepcopy(ledger[key][0]))
            with self.subTest(key=key):
                self.rejects(ledger, "duplicate")

    def test_rehashed_manifest_and_metadata_do_not_replace_original_authority(self):
        root = self.fixture()
        manifest = copy.deepcopy(self.manifest)
        manifest["files"][0]["sha256"] = "0" * 64
        data = (json.dumps(manifest, indent=2) + "\n").encode()
        (root / c.MANIFEST_REF).write_bytes(data)
        ledger = copy.deepcopy(self.ledger)
        ledger["inventory"][0]["sha256"] = "0" * 64
        ledger["provenance"]["manifest_sha256"] = hashlib.sha256(data).hexdigest()
        (root / c.LEDGER_REF).write_text(json.dumps(ledger), encoding="utf-8")
        self.assertNotEqual(c.digest(ledger), c.REVIEWED_DIGEST)
        with self.assertRaisesRegex(c.InputError, "original manifest bytes"):
            c.check(root)
        self.rejects(ledger, "authority mismatch")

    def test_wrong_original_hash_without_manifest_edit(self):
        ledger = copy.deepcopy(self.ledger)
        ledger["inventory"][0]["sha256"] = "0" * 64
        self.rejects(ledger, "inventory/hash")

    def test_unsupported_candidate_cannot_be_promoted(self):
        ledger = copy.deepcopy(self.ledger)
        ledger["variants"][1]["status"] = "supported_existing"
        self.rejects(ledger, "support/entry")
        ledger = copy.deepcopy(self.ledger)
        ledger["current_adapter"]["native_entry"] = "LBNLcryostat.tg"
        self.rejects(ledger, "adapter boundary")

    def test_material_definition_and_filename_are_not_source_physics(self):
        for key, value in (("actual_active_material", "AmO2"), ("particle", "ion"),
                           ("emission", "Am241_decay"), ("confine_volume", "active"),
                           ("unused_AmO2_is_activity_evidence", True)):
            with self.subTest(key=key):
                self.rejects(self.changed("original_macro", key, value), "source physics/material")

    def test_raw_parameter_is_not_modular_endcap_full_length(self):
        ledger = copy.deepcopy(self.ledger)
        endcap = next(r for r in ledger["primitive_solids"] if r["name"] == "endCap")
        endcap["full_axis_extents_mm"][2] = 165.5
        self.rejects(ledger, "curated metadata changed")
        ledger = copy.deepcopy(self.ledger)
        active = next(r for r in ledger["primitive_solids"] if r["name"] == "Active")
        active["full_axis_extents_mm"][2] = 0.004
        self.rejects(ledger, "curated metadata changed")

    def test_default_units_cannot_be_relabeled_explicit_or_cm(self):
        for key, value in (("tg_default_length", "cm"), ("selected_tg_explicit_unit_tokens", True),
                           ("macro_energy_token", "MeV"), ("inch_parameter_mm", 2.54)):
            with self.subTest(key=key):
                self.rejects(self.changed("units", key, value), "unit interpretation")

    def test_ledger_unknown_fields_and_fact_inputs_fail(self):
        ledger = copy.deepcopy(self.ledger)
        ledger["ledger_sha256"] = c.digest(ledger)
        self.rejects(ledger, "schema/keys")
        ledger = copy.deepcopy(self.ledger)
        ledger["parameters"][0]["file"] = "unknown.tg"
        self.rejects(ledger, "unknown fact")

    def test_unsafe_or_unknown_ledger_include(self):
        for target in ("../chamber.tg", "/chamber.tg", "sub/chamber.tg", "other.tg", "C:/source.tg"):
            ledger = copy.deepcopy(self.ledger)
            ledger["includes"][0]["targets"] = [target]
            with self.subTest(target=target):
                self.rejects(ledger, "locator|include")

    def test_lexical_unknown_traversing_and_duplicate_include(self):
        for replacement in ("#include ../shield.tg", "#include other.tg", "#include shield.tg\n#include shield.tg"):
            texts = self.texts()
            texts["stage.tg"] = texts["stage.tg"].replace("#include shield.tg", replacement)
            with self.subTest(replacement=replacement), self.assertRaisesRegex(c.InputError, "locator|include"):
                c.verify_selected_facts(self.ledger, texts)

    def test_original_byte_edit_fails_without_rerun(self):
        root = self.fixture(originals=True)
        path = root / ".local/transport/LBNL/stage.tg"
        path.write_bytes(path.read_bytes().replace(b":p Tcu 1.0", b":p Tcu 2.0"))
        with self.assertRaisesRegex(c.InputError, "original bytes changed: stage"):
            c.check(root, check_local=True)

    def test_selected_raw_material_parent_copy_and_macro_checks(self):
        edits = [("chamber.tg", ":p Lec 165.5", ":p Lec 155.0"),
                 ("LBNLcryostat.tg", "$ActiveThick/2 G4_Au", "$ActiveThick/2 AmO2"),
                 ("Am241.tg", ":place active -2 holder", ":place active -3 Holder"),
                 ("LBNLcryostat.mac", "/gps/particle gamma", "/gps/particle ion")]
        for name, old, new in edits:
            texts = self.texts()
            self.assertIn(old, texts[name])
            texts[name] = texts[name].replace(old, new)
            with self.subTest(name=name), self.assertRaises(c.InputError):
                c.verify_selected_facts(self.ledger, texts)

    def test_unused_material_cannot_be_used_elsewhere_unnoticed(self):
        texts = self.texts()
        texts["LBNLcryostat.tg"] += "\n:volu unexpected TUBE 0 1 1 AmO2\n"
        with self.assertRaisesRegex(c.InputError, "actual volume use"):
            c.verify_selected_facts(self.ledger, texts)

    def test_link_and_windows_reparse_inputs_are_refused(self):
        root = self.fixture()
        target = root / c.LEDGER_REF
        original = Path.lstat
        for mode, attributes in ((stat.S_IFLNK | 0o777, 0), (stat.S_IFREG | 0o644, stat.FILE_ATTRIBUTE_REPARSE_POINT)):
            def linked(path, **kwargs):
                if path == target:
                    class LinkInfo:
                        st_mode = mode
                        st_file_attributes = attributes
                        st_size = 10
                    return LinkInfo()
                return original(path, **kwargs)
            with self.subTest(mode=mode), patch.object(Path, "lstat", linked), self.assertRaisesRegex(c.InputError, "linked input"):
                c.check(root)

    def test_oversized_input_is_bounded(self):
        root = self.fixture()
        (root / c.LEDGER_REF).write_bytes(b" " * (c.MAX_JSON_BYTES + 1))
        with self.assertRaisesRegex(c.InputError, "oversized input"):
            c.check(root)

    def test_cli_is_read_only_and_labels_both_acceptance_limits(self):
        root = self.fixture()
        before = {ref: (root / ref).read_bytes() for ref in (c.LEDGER_REF, c.MANIFEST_REF)}
        output = io.StringIO()
        original = c.check
        with patch.object(c, "check", side_effect=lambda check_local=False: original(root, check_local)), contextlib.redirect_stdout(output):
            self.assertEqual(c.main(["--json"]), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result["verification_scope"], "source_input_verification_only")
        self.assertEqual(result["native_geometry_acceptance"], "not_run")
        self.assertEqual(before, {ref: (root / ref).read_bytes() for ref in before})
        self.assertFalse((root / ".local").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
