"""Read-only verification of a frozen cryostat input inventory, never a solver."""
import argparse
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import stat
import sys

ROOT = Path(__file__).absolute().parents[1]
MANIFEST_REF = "transport/cryostat-source.json"
LEDGER_REF = "transport/cryostat-input-ledger.json"
MANIFEST_SHA256 = "5967d5d0f8500a40f704bf653be2dc1a0f69e77239f643a8f7140533c9201e2a"
COMMIT = "1ff3371e0afb804115773af0541b3e56bd660f8c"
# Independent curated-metadata freeze, not a signature or physics acceptance.
REVIEWED_DIGEST = "40c3ba81b2d1d58e7d563c3f4da4ddfada8ae384816840a5a23f8c9355040d31"
SCOPE = "source_input_verification_only"
MAX_JSON_BYTES = 65536
TOP_KEYS = {"schema_version", "kind", "verification_scope", "provenance", "inventory",
            "units", "variants", "includes", "parameters", "primitive_solids",
            "placements", "material_definitions", "original_macro", "current_adapter",
            "unknowns", "references"}


class InputError(ValueError):
    pass


def require(condition, message):
    if not condition:
        raise InputError(message)


def relative_ref(value):
    require(type(value) is str and value and "\\" not in value and ":" not in value,
            "expected a portable relative locator")
    parts = value.split("/")
    require(not PurePosixPath(value).is_absolute() and all(p not in ("", ".", "..") for p in parts),
            "unsafe relative locator")
    return value


def read_bounded(project, ref, limit):
    """Reject symlinks/junctions at every project-relative component, then read bounded bytes."""
    relative_ref(ref)
    path = Path(project).absolute()
    for part in (None, *ref.split("/")):
        if part is not None:
            path /= part
        info = path.lstat()
        require(not stat.S_ISLNK(info.st_mode) and
                not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                "linked input refused: " + ref)
    require(stat.S_ISREG(info.st_mode) and info.st_size <= limit, "invalid/oversized input: " + ref)
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    require(len(data) <= limit, "oversized input: " + ref)
    return data


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        require(key not in result, "duplicate JSON key: " + key)
        result[key] = value
    return result


def finite_tree(value):
    if type(value) is float:
        require(math.isfinite(value), "nonfinite JSON number")
    elif type(value) is dict:
        for child in value.values():
            finite_tree(child)
    elif type(value) is list:
        for child in value:
            finite_tree(child)


def parse_json(data):
    try:
        value = json.loads(data.decode("utf-8"), object_pairs_hook=unique_object,
                           parse_constant=lambda token: (_ for _ in ()).throw(InputError("nonfinite JSON: " + token)))
    except (UnicodeError, json.JSONDecodeError, RecursionError) as error:
        raise InputError("invalid UTF-8 JSON") from error
    finite_tree(value)
    return value


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                     separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def rows_unique(rows, keys, label):
    require(type(rows) is list and rows, "invalid " + label + " rows")
    seen = set()
    for row in rows:
        require(type(row) is dict, "invalid " + label + " row type")
        identity = tuple(row.get(k) for k in keys)
        require(all(type(x) in (str, int) for x in identity), "invalid " + label + " identity")
        require(identity not in seen, "duplicate " + label + " identity")
        seen.add(identity)


def validate_ledger(ledger, manifest):
    require(type(ledger) is dict and set(ledger) == TOP_KEYS, "unsupported ledger schema/keys")
    finite_tree(ledger)
    require(type(ledger["schema_version"]) is int and ledger["schema_version"] == 1,
            "invalid schema version type/value")
    require(ledger["kind"] == "cryostat_source_input_ledger_v1" and ledger["verification_scope"] == SCOPE,
            "invalid verification boundary")
    provenance = ledger["provenance"]
    require(type(provenance) is dict and provenance.get("manifest_ref") == MANIFEST_REF and
            provenance.get("manifest_sha256") == MANIFEST_SHA256 and provenance.get("commit") == COMMIT,
            "original manifest/commit authority mismatch")
    require(manifest["commit"] == COMMIT and provenance["repository"] == manifest["repository"] and
            provenance["directory"] == manifest["directory"] and
            provenance["local_cache_ref"] == manifest["local_cache"], "provenance mismatch")
    rows_unique(ledger["inventory"], ("file",), "inventory")
    expected = {r["name"]: (r["bytes"], r["sha256"]) for r in manifest["files"]}
    found = {}
    for row in ledger["inventory"]:
        require(set(row) == {"file", "bytes", "sha256", "role"} and type(row["bytes"]) is int and
                type(row["sha256"]) is str and type(row["role"]) is str, "invalid inventory field/type")
        relative_ref(row["file"])
        require("/" not in row["file"], "inventory must use the exact nine source filenames")
        found[row["file"]] = (row["bytes"], row["sha256"])
    require(found == expected and len(found) == 9, "original source inventory/hash mismatch")
    rows_unique(ledger["variants"], ("id",), "variant")
    variants = {r["id"]: r for r in ledger["variants"]}
    require(set(variants) == {"modular", "monolithic"}, "unknown cryostat variant")
    for name, status, entry, closure in (
        ("modular", "supported_existing", "stage.tg", ["stage.tg", "shield.tg", "chamber.tg"]),
        ("monolithic", "candidate_input_only", "LBNLcryostat.tg", ["LBNLcryostat.tg"])):
        row = variants[name]
        require(row.get("status") == status and row.get("entry") == entry and row.get("include_closure") == closure,
                "support/entry/include closure mismatch: " + name)
        require(type(row.get("cavity_diameter_mm")) in (int, float) and row["cavity_diameter_mm"] == 67.7,
                "unsupported cavity dimension")
    units = ledger["units"]
    require(type(units) is dict and units.get("tg_default_length") == "mm" and
            units.get("tg_default_angle") == "deg" and units.get("tg_default_density") == "g/cm3" and
            units.get("inch_parameter_mm") == 25.4 and units.get("selected_tg_explicit_unit_tokens") is False and
            units.get("macro_length_token") == "mm" and units.get("macro_energy_token") == "keV",
            "default versus explicit unit interpretation mismatch")
    for label, keys in (("parameters", ("file", "name")), ("primitive_solids", ("file", "tag", "name")),
                        ("placements", ("file", "volume", "copy_number")),
                        ("material_definitions", ("file", "name")), ("includes", ("file",))):
        rows_unique(ledger[label], keys, label)
        for row in ledger[label]:
            require(row["file"] in found, "unknown fact input")
    for row in ledger["includes"]:
        require(type(row.get("targets")) is list, "invalid include targets")
        for target in row["targets"]:
            relative_ref(target)
            require(target in found and "/" not in target, "unknown include input")
    macro = ledger["original_macro"]
    require(type(macro) is dict and macro.get("file") == "LBNLcryostat.mac" and
            macro.get("particle") == "gamma" and macro.get("emission") == "monoenergetic_gamma" and
            macro.get("energy_keV") == 59.5 and macro.get("confine_volume") == "Active" and
            macro.get("actual_active_material") == "G4_Au" and macro.get("unused_AmO2_is_activity_evidence") is False,
            "source physics/material use mismatch")
    adapter = ledger["current_adapter"]
    require(type(adapter) is dict and adapter.get("id") == "lbnl_modular_nominal_v1" and
            adapter.get("native_entry") == "stage.tg" and type(adapter.get("native_expected_volume_count")) is int and
            adapter["native_expected_volume_count"] == 20, "existing adapter boundary mismatch")
    # Also freeze raw parameters, selected extents/placements, unknowns and limits.
    # A checksum supplied or recomputed by edited metadata grants no authority.
    require(digest(ledger) == REVIEWED_DIGEST, "reviewed curated metadata changed; independent review required")


def lexical_rows(text):
    return [line.split("//", 1)[0].split() for line in text.splitlines()
            if line.split("//", 1)[0].split()]


def one_directive(rows, tag, name):
    matches = [r for r in rows if len(r) >= 2 and r[0].lower() == ":" + tag and r[1] == name]
    require(len(matches) == 1, "missing/duplicate selected directive: " + name)
    return [matches[0][0].lower(), *matches[0][1:]]


def verify_selected_facts(ledger, texts):
    """Finite lexical checks only: no expressions, units or rotations are evaluated."""
    rows = {name: lexical_rows(text) for name, text in texts.items()}
    includes = {r["file"]: r["targets"] for r in ledger["includes"]}
    for name in (r["file"] for r in ledger["inventory"] if r["file"].endswith(".tg")):
        actual = []
        for row in rows[name]:
            if row[0].startswith("#include"):
                require(row[0] == "#include" and len(row) == 2, "malformed include")
                target = relative_ref(row[1])
                require(target in includes and "/" not in target, "unknown/traversing include")
                actual.append(target)
        require(actual == includes[name], "include closure mismatch: " + name)
    for fact in ledger["parameters"]:
        require(one_directive(rows[fact["file"]], "p", fact["name"]) ==
                [":p", fact["name"], fact["raw"]], "raw parameter mismatch: " + fact["name"])
    for fact in ledger["primitive_solids"]:
        expected = [":" + fact["tag"], fact["name"], fact["shape"], *fact["raw_arguments"]]
        if fact["material"] is not None:
            expected.append(fact["material"])
        require(one_directive(rows[fact["file"]], fact["tag"], fact["name"]) == expected,
                "selected solid/material mismatch: " + fact["name"])
    for fact in ledger["placements"]:
        expected = [":place", fact["volume"], str(fact["copy_number"]), fact["parent"],
                    fact["rotation"], *fact["raw_translation"]]
        require(one_directive(rows[fact["file"]], "place", fact["volume"]) == expected,
                "parent/copy/placement mismatch: " + fact["volume"])
    for fact in ledger["material_definitions"]:
        source = rows[fact["file"]]
        header = one_directive(source, "mixt_by_natoms", fact["name"])
        require(float(header[2]) == fact["density_g_cm3"] and int(header[3]) == len(fact["atoms"]),
                "material definition mismatch")
        atoms = header[4:]
        start = next(i for i, row in enumerate(source) if len(row) > 1 and
                     row[0].lower() == ":mixt_by_natoms" and row[1] == fact["name"]) + 1
        if not atoms:
            atoms = [token for row in source[start:start + len(fact["atoms"])] for token in row]
        require(atoms == [token for element, count in fact["atoms"].items() for token in (element, str(count))],
                "selected material atoms mismatch")
    require(not any(r[0].lower() == ":volu" and r[-1] == "AmO2" for r in rows["LBNLcryostat.tg"]),
            "AmO2 definition was mistaken for actual volume use")
    for fact in ledger["original_macro"]["commands"]:
        matches = [r for r in rows["LBNLcryostat.mac"] if r[0] == fact["command"]]
        require(matches == [[fact["command"], *fact["arguments"]]], "source macro mismatch: " + fact["command"])


def check(project=ROOT, check_local=False):
    manifest_bytes = read_bounded(project, MANIFEST_REF, MAX_JSON_BYTES)
    require(hashlib.sha256(manifest_bytes).hexdigest() == MANIFEST_SHA256, "pinned original manifest bytes changed")
    manifest = parse_json(manifest_bytes)
    ledger = parse_json(read_bounded(project, LEDGER_REF, MAX_JSON_BYTES))
    validate_ledger(ledger, manifest)
    if check_local:
        texts = {}
        for row in ledger["inventory"]:
            data = read_bounded(project, ".local/transport/LBNL/" + row["file"], row["bytes"])
            require(len(data) == row["bytes"] and hashlib.sha256(data).hexdigest() == row["sha256"],
                    "pinned original bytes changed: " + row["file"])
            texts[row["file"]] = data.decode("utf-8")
        verify_selected_facts(ledger, texts)
    return {"status": "passed", "verification_scope": SCOPE,
            "mode": "local_original_bytes_and_selected_facts" if check_local else "portable_curated_metadata_integrity",
            "inventory_files": 9, "local_source_files_read": 9 if check_local else 0,
            "native_geometry_acceptance": "not_run", "experimental_geometry_acceptance": "not_established",
            "science_calls": 0}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-local", action="store_true", help="read the existing nine pinned private cached originals")
    parser.add_argument("--json", action="store_true", help="emit one compact result object")
    args = parser.parse_args(argv)
    try:
        result = check(check_local=args.check_local)
    except (InputError, OSError, UnicodeError, KeyError, TypeError, ValueError, RecursionError) as error:
        result = {"status": "failed", "verification_scope": SCOPE, "error": str(error),
                  "native_geometry_acceptance": "not_run", "experimental_geometry_acceptance": "not_established"}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    elif result["status"] == "passed":
        print("Source-input verification passed: " + result["mode"] +
              "; local originals read=" + str(result["local_source_files_read"]) +
              ". Native geometry acceptance not run; experimental acceptance not established.")
    else:
        print("Source-input verification failed: " + result["error"] +
              ". Native geometry acceptance not run; experimental acceptance not established.", file=sys.stderr)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
