"""One bounded monolithic native structure/source-position audit; saved verification is read-only."""
import argparse
import datetime
import hashlib
import json
import math
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import time

import check_cryostat_inputs as inputs

ROOT = Path(__file__).absolute().parents[1]
BASE = ".local/m11f-cryostat-native-v1"
EXPECTED = "tools/native_cryostat_audit/expected.json"
EXPECTED_DIGEST = "399bd9f928157e73f4d59bcd707a361b637c4688b773a87eb6cf1e650781aaf9"
SCOPE = "bounded_native_structure_and_source_positions_only"
SOURCES = [".gitattributes", "tools/native_cryostat_audit/CMakeLists.txt", "tools/native_cryostat_audit/audit.cc",
           EXPECTED, "tools/cryostat_native_audit.py", "tools/test_cryostat_native_audit.py",
           "tools/NATIVE_CRYOSTAT_AUDIT.md", "tools/MAINTENANCE.md", "transport/README.md"]
LOCK_PINS = {"transport/pixi.toml": "87991463283a4f00b7e8a2758d9019c39ebe0fcad1387e87e500ed500f0638dd",
             "transport/pixi.lock": "c212a7f7e78bb7af4687bbbc7322659975961e62c3ea71a6f325e65e554b56be"}
HELPERS = {
    BASE + "/CONTROL-RUNTIME.sh": '''#!/usr/bin/env bash
set -euo pipefail
exec "$HOME/.pixi/bin/pixi" run --locked --no-install --manifest-path transport/pixi.toml "$@"
''',
    BASE + "/CONTROL-NATIVE.sh": '''#!/usr/bin/env bash
set -euo pipefail
set -C
printf '%s\\n' "$BASHPID" > "$1"
shift
exec timeout --signal=TERM --kill-after=5s 60s "$@"
''',
    BASE + "/CONTROL-CLEANUP.sh": '''#!/usr/bin/env bash
set -euo pipefail
read -r pid < "$1"
case "$pid" in ''|*[!0-9]*) exit 3;; esac
if [[ ! -e "/proc/$pid/cmdline" ]]; then exit 0; fi
cmdline=$(tr '\\0' '\\n' < "/proc/$pid/cmdline")
[[ "$cmdline" == *".local/m11f-cryostat-native-v1/build/cryostat_native_audit"* && "$cmdline" == *".local/m11f-cryostat-native-v1/native"* ]] || exit 4
kill -TERM -- "-$pid"
for step in 1 2 3 4 5; do
  if ! kill -0 -- "-$pid" 2>/dev/null; then exit 0; fi
  sleep 1
done
kill -KILL -- "-$pid"
''',
}
COMMON = {"kind", "schema_version", "status", "error", "runtime", "geant4_version_number",
          "elapsed_seconds", "stage_wall_seconds"}
SOLID_KEYS = {"id", "name", "entity_type", "constituents", "moved_solid_id",
              "moved_rotation_object", "moved_rotation_frame", "moved_translation_object_mm", "moved_translation_frame_mm"}
PHYSICAL_KEYS = {"name", "logical_name", "path", "copy_chain", "copy_number", "mother_path",
                 "translation_parent_mm", "translation_frame_mm", "rotation_object_to_parent",
                 "rotation_frame", "translation_global_mm", "rotation_object_to_global"}
GEOMETRY_KEYS = {"bounding_min_mm", "bounding_max_mm", "bounds_finite", "bounds_ordered",
                 "primitive_parameters", "primitive_parameters_valid", "volume_mm3", "volume_method"}
IDENTITY = [[1, 0, 0], [0, 1, 0], [0, 0, 1]]
require = inputs.require
AuditError = inputs.InputError


def utc():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def pin(project, ref):
    data = inputs.read_bounded(project, ref, 64 * 1024 * 1024)
    return {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)}


def load(project, ref):
    return inputs.parse_json(inputs.read_bounded(project, ref, 16 * 1024 * 1024))


def exclusive_json(path, value):
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2, allow_nan=False)
        stream.write("\n")


def exact_keys(value, keys, label):
    require(type(value) is dict and set(value) == set(keys), "unknown/missing " + label + " fields")


def number(value):
    require(type(value) in (int, float) and math.isfinite(value), "nonfinite/invalid numeric type")
    return value


def vector(value):
    require(type(value) is list and len(value) == 3, "invalid 3-vector")
    return [number(v) for v in value]


def close(a, b, tolerance=1e-10):
    if type(b) is list:
        require(type(a) is list and len(a) == len(b), "numeric shape mismatch")
        for x, y in zip(a, b):
            close(x, y, tolerance)
    else:
        require(abs(number(a) - number(b)) <= tolerance, "numeric value/frame/position mismatch")


def setting(actual, reviewed):
    """Numeric spelling may vary, but bool/string/null never aliases a number."""
    if type(reviewed) is dict:
        exact_keys(actual, reviewed, "GPS settings")
        for key, value in reviewed.items():
            setting(actual[key], value)
    elif type(reviewed) is list:
        require(type(actual) is list and len(actual) == len(reviewed), "GPS setting vector shape mismatch")
        for a, b in zip(actual, reviewed):
            setting(a, b)
    elif type(reviewed) in (int, float):
        close(actual, reviewed, 1e-12)
    else:
        require(type(actual) is type(reviewed) and actual == reviewed, "GPS setting type/value mismatch")


def transpose(matrix):
    return [list(row) for row in zip(*matrix)]


def mv(matrix, value):
    return [sum(a * b for a, b in zip(row, value)) for row in matrix]


def mm(a, b):
    return [[sum(a[i][k] * b[k][j] for k in range(3)) for j in range(3)] for i in range(3)]


def add(a, b):
    return [x + y for x, y in zip(a, b)]


def rotation(value):
    require(type(value) is list and len(value) == 3, "invalid rotation")
    for row in value:
        vector(row)
    close(mm(value, transpose(value)), IDENTITY, 1e-12)
    determinant = (value[0][0] * (value[1][1] * value[2][2] - value[1][2] * value[2][1]) -
                   value[0][1] * (value[1][0] * value[2][2] - value[1][2] * value[2][0]) +
                   value[0][2] * (value[1][0] * value[2][1] - value[1][1] * value[2][0]))
    close(determinant, 1, 1e-12)
    return value


def unique(rows, identity, label):
    require(type(rows) is list, "invalid " + label + " array")
    result = {}
    for row in rows:
        require(type(row) is dict, "invalid " + label + " row")
        key = identity(row)
        require(key not in result, "duplicate " + label + " identity")
        result[key] = row
    return result


def physical_key(row):
    require(type(row["path"]) is str and type(row["copy_chain"]) is list and row["copy_chain"] and
            all(type(x) is int for x in row["copy_chain"]), "invalid physical identity type")
    return row["path"], tuple(row["copy_chain"])


def expected(project=ROOT):
    value = load(project, EXPECTED)
    require(type(value) is dict and type(value.get("schema_version")) is int and value["schema_version"] == 1 and
            value.get("verification_scope") == SCOPE, "expected metadata schema/scope changed")
    require(inputs.digest(value) == EXPECTED_DIGEST, "reviewed expected facts changed despite metadata rehash")
    return value


def common(report, kind, fields, timings):
    exact_keys(report, COMMON | set(fields), kind)
    require(type(report["schema_version"]) is int and report["schema_version"] == 1 and
            report["kind"] == kind and report["status"] in
            ("completed", "completed_with_geometry_failures", "incomplete", "failed"), "invalid checkpoint kind/status")
    require(report["error"] is None or type(report["error"]) is str, "invalid native error")
    require(type(report["geant4_version_number"]) is int and report["geant4_version_number"] == 1132,
            "native Geant4 version mismatch")
    runtime = report["runtime"]
    exact_keys(runtime, {"geant4_version_number", "geant4_version", "compiler", "cplusplus", "rng_engine"}, "runtime")
    require(type(runtime["geant4_version_number"]) is int and runtime["geant4_version_number"] == 1132 and
            type(runtime["cplusplus"]) is int and runtime["cplusplus"] == 201703 and
            all(type(runtime[k]) is str and runtime[k] for k in ("geant4_version", "compiler", "rng_engine")), "invalid actual native runtime")
    require(number(report["elapsed_seconds"]) >= 0, "invalid native elapsed time")
    require(type(report["stage_wall_seconds"]) is dict and set(report["stage_wall_seconds"]) <= set(timings),
            "unknown stage timing fields")
    if report["status"].startswith("completed"):
        require(set(report["stage_wall_seconds"]) == set(timings), "missing completed stage timing fields")
    for value in report["stage_wall_seconds"].values():
        require(value is None or number(value) >= 0, "invalid stage wall time")
    if report["status"] == "completed":
        require(report["error"] is None and all(v is not None for v in report["stage_wall_seconds"].values()),
                "completed checkpoint has unknown/error stage")


def validate_solids(rows, facts, logicals):
    by_id = unique(rows, lambda r: r["id"], "solid")
    for identifier, row in by_id.items():
        exact_keys(row, SOLID_KEYS, "solid")
        require(type(identifier) is int and identifier >= 0 and type(row["name"]) is str and row["name"], "invalid solid ID/name")
        require(type(row["constituents"]) is list and all(type(x) is int and x in by_id for x in row["constituents"]),
                "invalid solid constituent ID")
    origins = {r["name"]: r for r in facts["authored_solids"]}
    authored = {name: [] for name in origins}
    helpers = set()
    edges = {r["name"]: r for r in facts["boolean_edges"]}
    for row in rows:
        if row["entity_type"] == "G4DisplacedSolid":
            helpers.add(row["id"])
            continue
        name = row["name"]
        require(name in origins and row["entity_type"] == origins[name]["entity_type"],
                "unknown extra native solid origin/type")
        authored[name].append(row)
        require(all(row[k] is None for k in SOLID_KEYS if k.startswith("moved_")), "authored solid reported as displaced")
        if name not in edges:
            require(row["constituents"] == [], "primitive has unexpected constituent edges")
    require(len(authored) == 47 and all(authored.values()) and len(helpers) <= len(edges),
            "native authored-origin/helper census mismatch")
    require(all(len(authored[name]) == 1 for name in edges), "duplicate Boolean origin instance")
    logical_origins = {r["solid_name"] for r in logicals.values()}
    require(all(len(authored[name]) == 1 for name in logical_origins), "cached logical solid origin repeated")
    visited, used_helpers, active = set(), set(), set()

    def visit(identifier, expected_name):
        row = by_id[identifier]
        require(row["name"] == expected_name and row["entity_type"] == origins[expected_name]["entity_type"],
                "wrong Boolean/logical/helper solid origin/type")
        require(identifier not in active, "cyclic native solid identity graph")
        if identifier in visited:
            return
        visited.add(identifier)
        active.add(identifier)
        if expected_name not in edges:
            active.remove(identifier)
            return
        edge = edges[expected_name]
        require(len(row["constituents"]) == 2, "wrong Boolean constituent count")
        visit(row["constituents"][0], edge["first"])
        second = row["constituents"][1]
        if second in helpers:
            helper = by_id[second]
            require(second not in used_helpers and helper["entity_type"] == "G4DisplacedSolid" and
                    helper["constituents"] == [] and type(helper["moved_solid_id"]) is int and helper["moved_solid_id"] in by_id,
                    "unclassified/reused native displaced helper")
            object_rotation = rotation(helper["moved_rotation_object"])
            close(rotation(helper["moved_rotation_frame"]), transpose(object_rotation), 1e-12)
            translation = vector(helper["moved_translation_object_mm"])
            close(vector(helper["moved_translation_frame_mm"]), [-x for x in mv(transpose(object_rotation), translation)])
            used_helpers.add(second)
            visited.add(second)
            visit(helper["moved_solid_id"], edge["second"])
        else:
            visit(second, edge["second"])
        active.remove(identifier)

    for row in logicals.values():
        require(type(row["solid_id"]) is int and row["solid_id"] in by_id, "logical/native solid identity mismatch")
        visit(row["solid_id"], row["solid_name"])
    require(visited == set(by_id) and used_helpers == helpers, "unreferenced extra native solid/helper")
    return authored, by_id


def validate_materials(logicals, facts):
    found = unique(logicals, lambda r: r["name"], "logical volume")
    require(set(found) == {r["name"] for r in facts["logical_volumes"]} and len(found) == 22,
            "logical volume census mismatch")
    materials = {}
    for fact in facts["logical_volumes"]:
        row = found[fact["name"]]
        exact_keys(row, {"name", "material", "solid_name", "solid_id", "density_g_cm3", "elements"}, "logical volume")
        require(row["material"] == fact["material"] and row["solid_name"] == fact["solid_name"],
                "logical solid/material use mismatch")
        require(number(row["density_g_cm3"]) > 0 and type(row["elements"]) is list and row["elements"], "invalid native material")
        fractions = []
        symbols = set()
        for element in row["elements"]:
            exact_keys(element, {"name", "symbol", "z", "a_g_mole", "mass_fraction"}, "material element")
            require(type(element["name"]) is str and type(element["symbol"]) is str and element["symbol"] not in symbols,
                    "invalid/duplicate native element")
            symbols.add(element["symbol"])
            require(number(element["z"]) > 0 and number(element["a_g_mole"]) > 0 and
                    0 < number(element["mass_fraction"]) <= 1, "invalid native element quantity")
            fractions.append(element["mass_fraction"])
        close(math.fsum(fractions), 1, 1e-10)
        value = row["density_g_cm3"], row["elements"]
        require(row["material"] not in materials or materials[row["material"]] == value, "inconsistent repeated native material")
        materials[row["material"]] = value
    require(set(materials) == set(facts["material_uses"]) and len(materials) == 11 and "AmO2" not in materials,
            "actual used material census mismatch")
    gold = materials["G4_Au"][1]
    require(len(gold) == 1 and gold[0]["symbol"] == "Au" and gold[0]["z"] == 79 and gold[0]["mass_fraction"] == 1,
            "Active G4_Au elemental identity mismatch")
    for fact in facts["custom_materials"]:
        density, elements = materials[fact["name"]]
        close(density, fact["density_g_cm3"], 1e-12)
        counts = {e["symbol"]: e["mass_fraction"] / e["a_g_mole"] for e in elements}
        require(set(counts) == set(fact["atomic_counts"]), "custom material elements mismatch")
        ratios = [counts[name] / count for name, count in fact["atomic_counts"].items()]
        close([r / ratios[0] for r in ratios], [1] * len(ratios), 1e-10)
    return found


def validate_physical(rows, facts):
    found = unique(rows, physical_key, "physical volume")
    expected_rows = {physical_key(r): r for r in facts["physical_identities"]}
    require(set(found) == set(expected_rows) and len(found) == 23, "physical ancestry/copy census mismatch")
    for key, row in found.items():
        exact_keys(row, PHYSICAL_KEYS, "physical volume")
        for field in ("name", "logical_name", "path", "copy_chain", "copy_number", "mother_path"):
            require(type(row[field]) is type(expected_rows[key][field]) and row[field] == expected_rows[key][field],
                    "physical name/copy/ancestry mismatch")
        object_rotation = rotation(row["rotation_object_to_parent"])
        close(rotation(row["rotation_frame"]), transpose(object_rotation), 1e-12)
        translation = vector(row["translation_parent_mm"])
        # Physical-volume getter is -t; displaced-solid getter above is -R^T*t.
        close(vector(row["translation_frame_mm"]), [-x for x in translation])
        if row["mother_path"] is None:
            close(row["rotation_object_to_global"], object_rotation, 1e-12)
            close(row["translation_global_mm"], translation)
        else:
            parent = found[(row["mother_path"], tuple(row["copy_chain"][:-1]))]
            close(rotation(row["rotation_object_to_global"]), mm(parent["rotation_object_to_global"], object_rotation), 1e-12)
            close(vector(row["translation_global_mm"]), add(parent["translation_global_mm"], mv(parent["rotation_object_to_global"], translation)))
    source = facts["source"]
    active = found[(source["active_path"], tuple(source["active_copy_chain"]))]
    holder = found[("/lab/Holder", (0, -5))]
    for row, target in ((active, source["active_to_holder"]), (holder, source["holder_to_world"])):
        close(row["rotation_object_to_parent"], target["object_rotation"], 1e-12)
        close(row["translation_parent_mm"], target["translation_mm"])
    close(holder["rotation_frame"], source["holder_to_world"]["frame_rotation"], 1e-12)
    close(active["translation_global_mm"], source["active_to_world"]["translation_mm"])
    close(active["rotation_object_to_global"], source["active_to_world"]["object_rotation"], 1e-12)
    return found, active


def validate_import(report, facts):
    common(report, "cryostat_native_import_v1", {"logical_volumes", "physical_volumes", "solids"},
           {"native_import", "census_materials_transforms"})
    logicals = validate_materials(report["logical_volumes"], facts)
    authored, by_id = validate_solids(report["solids"], facts, logicals)
    physicals, active = validate_physical(report["physical_volumes"], facts)
    return authored, by_id, physicals, active


def source_point(row, active):
    global_position = vector(row["global_mm"])
    local_position = mv(transpose(active["rotation_object_to_global"]),
                        [a - b for a, b in zip(global_position, active["translation_global_mm"])])
    close(vector(row["source_local_mm"]), local_position, 1e-10)
    return local_position


def validate_geometry(report, imported, facts, active):
    common(report, "cryostat_native_geometry_v1", {"solids", "overlaps", "probes", "overlap_seed", "overlap_samples"},
           {"solid_diagnostics", "overlaps"})
    require(type(report["overlap_seed"]) is int and report["overlap_seed"] == 26092632 and
            type(report["overlap_samples"]) is int and report["overlap_samples"] == 10000, "overlap budget changed")
    for row in report["solids"]:
        exact_keys(row, SOLID_KEYS | GEOMETRY_KEYS, "geometry solid")
        require(type(row["id"]) is int and row["id"] >= 0, "invalid geometry solid ID type/value")
        require(type(row["constituents"]) is list and all(type(value) is int for value in row["constituents"]),
                "invalid geometry constituent ID type")
        if row["entity_type"] == "G4DisplacedSolid":
            require(type(row["moved_solid_id"]) is int, "invalid geometry moved-solid ID type")
        else:
            require(row["moved_solid_id"] is None, "non-displaced geometry moved-solid ID must be null")
    rows = unique(report["solids"], lambda r: r["id"], "geometry solid")
    original = {r["id"]: r for r in imported["solids"]}
    require(set(rows) == set(original), "geometry/native store census mismatch")
    issues = []
    primitive_origins = {}
    for identifier, row in rows.items():
        exact_keys(row, SOLID_KEYS | GEOMETRY_KEYS, "geometry solid")
        require({k: row[k] for k in SOLID_KEYS} == original[identifier], "native solid identity changed between checkpoints")
        require(type(row["bounds_finite"]) is bool and type(row["bounds_ordered"]) is bool, "invalid native bounds flags")
        if row["bounding_min_mm"] is None or row["bounding_max_mm"] is None:
            issues.append("unknown bounds: " + row["name"])
        else:
            low, high = vector(row["bounding_min_mm"]), vector(row["bounding_max_mm"])
            if not row["bounds_finite"] or not row["bounds_ordered"] or not all(a < b for a, b in zip(low, high)):
                issues.append("invalid/degenerate bounds: " + row["name"])
        params = row["primitive_parameters"]
        require(type(params) is dict, "invalid primitive parameter object")
        if row["entity_type"] == "G4Box":
            exact_keys(params, {"half_lengths_mm"}, "box primitive")
            half = vector(params["half_lengths_mm"])
            valid = all(v > 0 for v in half)
            analytic = 8 * math.prod(half)
        elif row["entity_type"] == "G4Tubs":
            exact_keys(params, {"inner_radius_mm", "outer_radius_mm", "half_length_mm", "start_angle_rad", "delta_angle_rad"}, "tube primitive")
            r0, r1, h, start, delta = [number(params[k]) for k in ("inner_radius_mm", "outer_radius_mm", "half_length_mm", "start_angle_rad", "delta_angle_rad")]
            valid = 0 <= r0 < r1 and h > 0 and 0 < delta <= 2 * math.pi + 1e-12
            analytic = (r1 * r1 - r0 * r0) * h * delta
        else:
            require(params == {} and row["primitive_parameters_valid"] is None and row["volume_mm3"] is None,
                    "Boolean/helper unknown volume must remain null")
            require(row["volume_method"] == ("not_run_stochastic_boolean" if row["entity_type"] in
                    ("G4UnionSolid", "G4SubtractionSolid") else "not_applicable"), "unscoped stochastic volume was substituted")
            continue
        require(type(row["primitive_parameters_valid"]) is bool and row["volume_method"] == "analytic_primitive",
                "primitive diagnostic method/type mismatch")
        if not valid or not row["primitive_parameters_valid"] or row["volume_mm3"] is None or number(row["volume_mm3"]) <= 0:
            issues.append("invalid primitive dimensions/volume: " + row["name"])
        else:
            require(math.isclose(row["volume_mm3"], analytic, rel_tol=1e-12, abs_tol=1e-12), "primitive analytic volume mismatch")
        if row["name"] == "Active":
            close(params["outer_radius_mm"], facts["source"]["radius_mm"], 1e-12)
            close(params["half_length_mm"], facts["source"]["half_length_mm"], 1e-12)
        instance_geometry = params, row["bounding_min_mm"], row["bounding_max_mm"]
        require(row["name"] not in primitive_origins or primitive_origins[row["name"]] == instance_geometry,
                "same-origin primitive parameters/bounds differ")
        primitive_origins[row["name"]] = instance_geometry
    overlap_issues = []
    overlaps = unique(report["overlaps"], physical_key, "overlap")
    expected_overlaps = {physical_key(r) for r in facts["physical_identities"] if r["mother_path"] is not None}
    if report["stage_wall_seconds"]["overlaps"] is None:
        require(report["status"] == "completed_with_geometry_failures" and not overlaps, "overlap observations falsely marked unexecuted")
        overlap_issues.append("overlaps not executed after invalid structural/primitive diagnostics")
    else:
        require(set(overlaps) == expected_overlaps, "overlap placement census mismatch")
    for row in overlaps.values():
        exact_keys(row, {"path", "copy_chain", "reported_overlap"}, "overlap")
        require(type(row["reported_overlap"]) is bool, "invalid overlap flag type")
        if row["reported_overlap"]:
            overlap_issues.append("sampled overlap reported: " + row["path"] + " " + str(row["copy_chain"]))
    probes = unique(report["probes"], lambda r: r["name"], "source probe")
    require(set(probes) == {r["name"] for r in facts["probes"]}, "source probe census mismatch")
    for fact in facts["probes"]:
        row = probes[fact["name"]]
        exact_keys(row, {"name", "source_local_mm", "global_mm", "source_inside", "expected_source_inside"}, "source probe")
        close(source_point(row, active), fact["source_local_mm"], 1e-10)
        require(row["expected_source_inside"] == fact["expected_source_inside"], "source probe expectation changed")
        if row["source_inside"] != fact["expected_source_inside"]:
            issues.append("native source probe failed: " + row["name"])
    return {"solid_diagnostics": issues, "overlaps": overlap_issues}


def validate_gps(report, facts, active):
    common(report, "cryostat_native_gps_v1", {"original_settings", "native_getters", "seed", "requested_positions", "positions",
           "raw_internal_rejection_count_unknown"}, {"gps_position_confinement"})
    setting(report["original_settings"], facts["gps"]["original_settings"])
    setting(report["native_getters"], facts["gps"]["native_getters"])
    require(type(report["seed"]) is int and report["seed"] == 26100161 and
            type(report["requested_positions"]) is int and report["requested_positions"] == 1000 and
            report["raw_internal_rejection_count_unknown"] is None, "GPS seed/count/unknown rejection counter mismatch")
    positions = unique(report["positions"], lambda r: r["index"], "GPS position")
    require(set(positions) == set(range(1000)) and all(type(k) is int for k in positions), "GPS returned position census mismatch")
    source = facts["source"]
    for row in positions.values():
        exact_keys(row, {"index", "global_mm", "source_local_mm", "source_inside", "native_navigator_identity"}, "GPS position")
        local = source_point(row, active)
        require(math.hypot(local[0], local[1]) < source["radius_mm"] and abs(local[2]) < source["half_length_mm"] and
                row["source_inside"] == "inside", "returned GPS point is not strict Active interior")
        navigator = row["native_navigator_identity"]
        exact_keys(navigator, {"name", "logical_name", "path", "copy_chain", "copy_number"}, "native navigator identity")
        require(type(navigator["copy_chain"]) is list and all(type(value) is int for value in navigator["copy_chain"]),
                "invalid navigator copy-chain integer type")
        require(type(navigator["copy_number"]) is int, "invalid navigator copy-number integer type")
        require(navigator == {"name": "Active", "logical_name": "Active", "path": source["active_path"],
                             "copy_chain": source["active_copy_chain"], "copy_number": -2}, "navigator did not identify exact Active ancestry/copy")
    return len(positions)


def inspect_reports(reports, facts):
    stages = {k: "not_executed" for k in ("native_import", "census_materials_transforms", "solid_diagnostics", "overlaps", "gps_position_confinement")}
    summary = {"status": "failed_native_import", "stages": stages, "issues": [], "logical_count": None,
               "physical_count": None, "native_solid_count": None, "authored_origin_count": None,
               "primitive_boolean_instance_count": None, "displaced_helper_count": None,
               "gps_positions": None, "scoped_acceptance": False}
    imported = reports.get("import.json")
    try:
        if imported is None:
            return summary
        common(imported, "cryostat_native_import_v1", {"logical_volumes", "physical_volumes", "solids"}, {"native_import", "census_materials_transforms"})
        for field, target in (("logical_volumes", "logical_count"), ("physical_volumes", "physical_count"), ("solids", "native_solid_count")):
            require(imported[field] is None or type(imported[field]) is list, "invalid partial import array")
            summary[target] = len(imported[field]) if imported[field] is not None else None
        if imported["status"] != "completed":
            summary["logical_count"] = summary["physical_count"] = summary["native_solid_count"] = None
            stages["native_import"] = "incomplete"
            summary["issues"].append(imported["error"] or "partial native import")
            return summary
        authored, by_id, _, active = validate_import(imported, facts)
        summary["authored_origin_count"] = len(authored)
        summary["displaced_helper_count"] = sum(r["entity_type"] == "G4DisplacedSolid" for r in by_id.values())
        summary["primitive_boolean_instance_count"] = len(by_id) - summary["displaced_helper_count"]
        stages["native_import"] = stages["census_materials_transforms"] = "passed"
        summary["status"] = "failed_native_audit"
        geometry = reports.get("geometry.json")
        geometry_passed = False
        if geometry is not None:
            common(geometry, "cryostat_native_geometry_v1", {"solids", "overlaps", "probes", "overlap_seed", "overlap_samples"}, {"solid_diagnostics", "overlaps"})
            require(geometry["runtime"] == imported["runtime"], "native runtime/RNG engine changed between checkpoints")
            if geometry["status"].startswith("completed"):
                issues = validate_geometry(geometry, imported, facts, active)
                summary["issues"].extend(issues["solid_diagnostics"] + issues["overlaps"])
                geometry_passed = not any(issues.values()) and geometry["status"] == "completed"
                for stage in issues:
                    stages[stage] = "failed" if issues[stage] else "passed"
                if geometry["stage_wall_seconds"]["overlaps"] is None:
                    stages["overlaps"] = "not_executed"
            else:
                stages["solid_diagnostics"] = stages["overlaps"] = "incomplete"
                summary["issues"].append(geometry["error"] or "partial native geometry diagnostics")
        gps = reports.get("gps.json")
        gps_passed = False
        if gps is not None:
            common(gps, "cryostat_native_gps_v1", {"original_settings", "native_getters", "seed", "requested_positions", "positions", "raw_internal_rejection_count_unknown"}, {"gps_position_confinement"})
            require(gps["runtime"] == imported["runtime"], "native runtime/RNG engine changed between checkpoints")
            require(gps["positions"] is None or type(gps["positions"]) is list, "invalid partial GPS array")
            summary["gps_positions"] = len(gps["positions"]) if gps["positions"] is not None else None
            if gps["stage_wall_seconds"].get("gps_position_confinement") is None:
                summary["gps_positions"] = None
            if gps["status"] == "completed":
                summary["gps_positions"] = validate_gps(gps, facts, active)
                stages["gps_position_confinement"] = "passed"
                gps_passed = True
            else:
                stages["gps_position_confinement"] = "incomplete"
                summary["issues"].append(gps["error"] or "partial native GPS confinement")
        if geometry_passed and gps_passed:
            summary["status"] = "complete_native_audit"
            summary["scoped_acceptance"] = True
        elif geometry is not None and geometry["status"] == "completed_with_geometry_failures":
            summary["status"] = "completed_with_geometry_failures"
        elif geometry is not None and (stages["solid_diagnostics"] == "failed" or stages["overlaps"] == "failed"):
            summary["status"] = "completed_with_geometry_failures"
    except (AuditError, KeyError, TypeError, ValueError) as error:
        summary["status"] = "failed_native_audit"
        summary["issues"].append(str(error))
    return summary


def read_reports(project):
    reports, errors = {}, []
    native = Path(project) / BASE / "native"
    if native.exists():
        for ancestor in (Path(project).absolute(), Path(project).absolute() / ".local", Path(project).absolute() / BASE, native):
            info = ancestor.lstat()
            require(stat.S_ISDIR(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    "linked/invalid native output directory")
        for path in native.iterdir():
            if path.name not in ("import.json", "geometry.json", "gps.json"):
                errors.append("unknown native checkpoint file: " + path.name)
    for name in ("import.json", "geometry.json", "gps.json"):
        ref = BASE + "/native/" + name
        if (Path(project) / ref).exists():
            try:
                reports[name] = load(project, ref)
            except (AuditError, OSError, ValueError) as error:
                errors.append(name + ": " + str(error))
    return reports, errors


def frozen_sources(project):
    freeze = load(project, BASE + "/SOURCE-FREEZE.json")
    require(freeze.get("kind") == "m11f_source_freeze_v1" and type(freeze.get("source_records")) is dict,
            "missing root source freeze")
    require(set(freeze["source_records"]) == set(SOURCES), "source-freeze scope mismatch")
    for ref, record in freeze["source_records"].items():
        require(pin(project, ref) == {k: record[k] for k in ("sha256", "bytes")}, "changed frozen source: " + ref)
    # Private AI exits are optional for ordinary manual contributions. Root supplies
    # them for this owned round and independently enforces its actual exit barrier.
    exits = freeze.get("writer_exits", {})
    require(type(exits) is dict and set(exits) <= {"control", "native"}, "invalid optional writer exit records")
    for label, record in exits.items():
        ref = record["path"]
        prefix = "CONTROL" if label == "control" else "NATIVE"
        require(ref.startswith(BASE + "/") and re.fullmatch(prefix + r"-EXIT(?:-v[1-9][0-9]*)?\.json", ref[len(BASE) + 1:]) and
                pin(project, ref)["sha256"] == record["sha256"], "writer exit identity changed")
        exit_record = load(project, ref)
        terminal = exit_record.get("status") == "exited"
        if label == "native":
            require(exit_record.get("kind") in {"m11f_native_writer_exit_v1", "m11f_native_writer_exit_v2"},
                    "unknown native writer exit kind")
            # The immutable native v1/v2 receipts predate the control status field.
            # Root separately verifies actual completion and these pinned receipts.
            terminal = "status" not in exit_record or terminal
        require(exit_record.get("no_more_source_writes") is True and terminal,
                "implementation writer has not exited: " + label)
    return freeze["source_records"]


def consumed_inputs(project):
    inputs.check(project, check_local=True)
    records = {ref: pin(project, ref) for ref in (inputs.LEDGER_REF, inputs.MANIFEST_REF, "tools/check_cryostat_inputs.py", *LOCK_PINS)}
    for ref, digest in LOCK_PINS.items():
        require(records[ref]["sha256"] == digest, "locked runtime input changed: " + ref)
    for item in load(project, inputs.MANIFEST_REF)["files"]:
        ref = ".local/transport/LBNL/" + item["name"]
        records[ref] = pin(project, ref)
    return records


def new_path(project, ref):
    inputs.relative_ref(ref)
    require(ref.startswith(BASE + "/") and
            (ref[len(BASE) + 1:] in ("build", "native", "SOURCE-FREEZE.json", "source-frozen") or
             ref[len(BASE) + 1:] in {"source-frozen/" + source for source in SOURCES} or
             ref[len(BASE) + 1:].startswith("CONTROL-")), "output must use the exact M11f audit root")
    path = Path(project).absolute()
    for part in (None, *ref.split("/")):
        if part is not None:
            path /= part
        try:
            info = path.lstat()
            require(not stat.S_ISLNK(info.st_mode) and not (getattr(info, "st_file_attributes", 0) & stat.FILE_ATTRIBUTE_REPARSE_POINT),
                    "linked output component refused")
        except FileNotFoundError:
            pass
    require(not path.exists(), "no-clobber output already exists: " + ref)
    return path


def helper_records(project):
    records = {}
    for ref, script in HELPERS.items():
        expected_bytes = script.encode("utf-8")
        records[ref] = pin(project, ref)
        require(records[ref] == {"sha256": hashlib.sha256(expected_bytes).hexdigest(), "bytes": len(expected_bytes)},
                "code-owned runtime helper changed: " + ref)
    return records


def write_helpers(project):
    # Validate every fixed output before creating any helper, preserving old attempts.
    paths = {ref: new_path(project, ref) for ref in HELPERS}
    for ref, path in paths.items():
        with path.open("xb") as stream:
            stream.write(HELPERS[ref].encode("utf-8"))
    return helper_records(project)


def runtime_command(project, arguments):
    # No inline shell program crosses Windows command-line quoting. Bash reads
    # the code-pinned LF file and receives each remaining item as an argument.
    script = BASE + "/CONTROL-RUNTIME.sh"
    if os.name == "nt":
        return ["wsl.exe", "--distribution", "Ubuntu-24.04", "--cd", str(Path(project).absolute()), "--exec", "bash", script, *arguments]
    return ["bash", script, *arguments]


def command(project, name, arguments, timeout):
    base = Path(project) / BASE
    helpers = helper_records(project)
    stdout_ref, stderr_ref = BASE + "/CONTROL-" + name + ".stdout.log", BASE + "/CONTROL-" + name + ".stderr.log"
    cmd = runtime_command(project, arguments)
    start, started = utc(), time.perf_counter()
    returncode, error, timed_out = None, None, False
    with new_path(project, stdout_ref).open("xb") as stdout, new_path(project, stderr_ref).open("xb") as stderr:
        try:
            result = subprocess.run(cmd, cwd=project, stdout=stdout, stderr=stderr, timeout=timeout, check=False)
            returncode = result.returncode
            timed_out = name == "NATIVE" and returncode in (124, 137)
        except subprocess.TimeoutExpired:
            timed_out = True
            error = "host command timeout at " + str(timeout) + " seconds"
        except OSError as exc:
            error = str(exc)
    result = {"kind": "m11f_control_command_v1", "command": cmd, "started_utc": start, "ended_utc": utc(),
              "elapsed_seconds": time.perf_counter() - started, "return_code": returncode, "timed_out": timed_out,
              "error": error, "stdout": stdout_ref, "stderr": stderr_ref, "helper_records": helpers}
    exclusive_json(base / ("CONTROL-" + name + ".json"), result)
    return result


def freeze(project=ROOT):
    """Explicit manual source snapshot; no private supervisor state or solver."""
    expected(project)
    base = Path(project) / BASE
    if not base.exists():
        new_path(project, BASE + "/CONTROL-PREFLIGHT.json")
        base.mkdir(parents=True)
    records = {ref: pin(project, ref) for ref in SOURCES}
    receipt_path = new_path(project, BASE + "/SOURCE-FREEZE.json")
    snapshot_root = new_path(project, BASE + "/source-frozen")
    snapshots = {ref: new_path(project, BASE + "/source-frozen/" + ref) for ref in SOURCES}
    snapshot_root.mkdir()
    for ref, path in snapshots.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("xb") as stream:
            stream.write(inputs.read_bounded(project, ref, 64 * 1024 * 1024))
        require(pin(project, BASE + "/source-frozen/" + ref) == records[ref], "changed source while freezing snapshot")
    exclusive_json(receipt_path,
                   {"kind": "m11f_source_freeze_v1", "utc": utc(), "source_records": records})
    return records


def native_arguments():
    # The native-only GNU timeout owns its process group. Its own PID marker is
    # exclusive and allows precise cleanup if the host WSL bridge times out.
    return ["bash", BASE + "/CONTROL-NATIVE.sh", BASE + "/CONTROL-NATIVE.pid",
            BASE + "/build/cryostat_native_audit", ".local/transport/LBNL/LBNLcryostat.tg", BASE + "/native"]


def cleanup_arguments():
    # Refuse a reused/foreign PID: the exact compiled binary/output argv must
    # still occur in the Linux supervisor cmdline before its group is signalled.
    return ["bash", BASE + "/CONTROL-CLEANUP.sh", BASE + "/CONTROL-NATIVE.pid"]


def run(project=ROOT):
    facts = expected(project)
    sources = frozen_sources(project)
    new_path(project, BASE + "/build")
    new_path(project, BASE + "/native")
    started = time.perf_counter()
    receipt_path = new_path(project, BASE + "/CONTROL-RUN.json")
    input_pins = consumed_inputs(project)
    helpers = write_helpers(project)
    exclusive_json(new_path(project, BASE + "/CONTROL-START.json"), {"kind": "m11f_control_start_v1", "utc": utc(), "source_records": sources, "input_records": input_pins, "helper_records": helpers})
    receipt = {"kind": "m11f_control_run_v1", "schema_version": 1, "verification_scope": SCOPE,
               "started_utc": utc(), "source_records": sources, "input_records": input_pins,
               "helper_records": helpers,
               "binary_record": None, "commands": {}, "checkpoint_records": {}, "log_records": {},
               "actual_versions": {}, "native_invocations": 0, "error": None, "radiation_calls": 0, "SSD_calls": 0,
               "adapter_eligibility": "unchanged_candidate_input_only", "experimental_acceptance": "not_established"}
    try:
        for name, args in (("REMAGE-VERSION", ["remage", "--version"]), ("GEANT4-VERSION", ["geant4-config", "--version"]),
                           ("CMAKE-VERSION", ["cmake", "--version"]), ("COMPILER-VERSION", ["c++", "--version"]),
                           ("TIMEOUT-VERSION", ["timeout", "--version"]),
                           ("CONFIGURE", ["cmake", "-S", "tools/native_cryostat_audit", "-B", BASE + "/build", "-G", "Ninja"]),
                           ("BUILD", ["cmake", "--build", BASE + "/build", "--parallel", "2", "--target", "cryostat_native_audit"])):
            result = command(project, name, args, 120)
            receipt["commands"][name] = result
            require(result["return_code"] == 0 and not result["timed_out"] and result["error"] is None,
                    "locked runtime/configure/build command failed: " + name)
            if name.endswith("VERSION"):
                text = inputs.read_bounded(project, result["stdout"], 65536).decode("utf-8").strip()
                receipt["actual_versions"][name] = text
                if name == "GEANT4-VERSION":
                    require(text == "11.3.2", "actual Geant4 version changed")
                if name == "REMAGE-VERSION":
                    require(text == "1.1.0", "actual remage version changed")
        require(frozen_sources(project) == sources and consumed_inputs(project) == input_pins, "source/input freeze changed during build")
        receipt["binary_record"] = pin(project, BASE + "/build/cryostat_native_audit")
        exclusive_json(new_path(project, BASE + "/CONTROL-BINARY.json"), {"kind": "m11f_compiled_binary_freeze_v1", "utc": utc(), "binary_record": receipt["binary_record"]})
        receipt["native_invocations"] = 1
        new_path(project, BASE + "/CONTROL-NATIVE.pid")
        result = command(project, "NATIVE", native_arguments(), 120)
        receipt["commands"]["NATIVE"] = result
        receipt["native_worker_cleanup"] = "native_timeout_supervisor_returned" if result["error"] is None else "unknown_requires_owned_worker_inspection"
        if result["error"] is not None and result["timed_out"]:
            cleanup = command(project, "NATIVE-CLEANUP", cleanup_arguments(), 20)
            receipt["commands"]["NATIVE-CLEANUP"] = cleanup
            receipt["native_worker_cleanup"] = "owned_group_cleanup_returned" if cleanup["return_code"] == 0 else "unknown_requires_owned_worker_inspection"
        require(pin(project, BASE + "/build/cryostat_native_audit") == receipt["binary_record"], "binary changed during native inspection")
    except (AuditError, OSError, ValueError) as error:
        receipt["error"] = str(error)
    finally:
        try:
            require(frozen_sources(project) == sources and consumed_inputs(project) == input_pins, "source/input freeze changed after execution")
            require(helper_records(project) == helpers, "runtime helpers changed after execution")
        except (AuditError, OSError, ValueError) as error:
            receipt["error"] = str(error)
        reports, errors = read_reports(project)
        receipt["inspection"] = inspect_reports(reports, facts)
        receipt["inspection"]["issues"].extend(errors)
        for name in ("import.json", "geometry.json", "gps.json"):
            if (Path(project) / BASE / "native" / name).exists():
                receipt["checkpoint_records"][name] = pin(project, BASE + "/native/" + name)
        for result in receipt["commands"].values():
            for field in ("stdout", "stderr"):
                receipt["log_records"][result[field]] = pin(project, result[field])
        native = receipt["commands"].get("NATIVE")
        if native and native["timed_out"]:
            receipt["inspection"]["status"] = "timed_out_partial"
            receipt["inspection"]["scoped_acceptance"] = False
        elif receipt["error"] or errors or not native or native["return_code"] != 0:
            receipt["inspection"]["scoped_acceptance"] = False
            if receipt["inspection"]["status"] == "complete_native_audit":
                receipt["inspection"]["status"] = "failed_native_audit"
        if native:
            logs = b"\n".join(inputs.read_bounded(project, native[k], 64 * 1024 * 1024) for k in ("stdout", "stderr"))
            receipt["native_warning_or_error_log"] = bool(re.search(rb"\b(?:warning|fatal|error)\b|G4Exception", logs, re.I))
            if receipt["native_warning_or_error_log"] and receipt["inspection"]["status"] == "complete_native_audit":
                receipt["inspection"]["status"] = "completed_with_native_warnings"
                receipt["inspection"]["scoped_acceptance"] = False
        else:
            receipt["native_warning_or_error_log"] = None
        receipt["ended_utc"] = utc()
        receipt["elapsed_seconds"] = time.perf_counter() - started
        exclusive_json(receipt_path, receipt)
    return receipt


def saved_artifacts(project, receipt):
    require(consumed_inputs(project) == receipt["input_records"], "saved input identity changed")
    require(helper_records(project) == receipt["helper_records"], "saved runtime helper identity changed")
    for result in receipt["commands"].values():
        require(result["helper_records"] == receipt["helper_records"], "saved command helper identity changed")
    if receipt["binary_record"] is not None:
        require(pin(project, BASE + "/build/cryostat_native_audit") == receipt["binary_record"], "saved binary identity changed")
    for ref, record in receipt["log_records"].items():
        require(ref.startswith(BASE + "/CONTROL-") and pin(project, ref) == record, "saved log changed")
    reports, errors = read_reports(project)
    actual_names = {name for name in ("import.json", "geometry.json", "gps.json") if (Path(project) / BASE / "native" / name).exists()}
    require(actual_names == set(receipt["checkpoint_records"]), "saved checkpoint census mismatch")
    for name, record in receipt["checkpoint_records"].items():
        require(pin(project, BASE + "/native/" + name) == record, "saved checkpoint bytes changed")
    return reports, errors


def interpret_saved(receipt, reports, errors, facts, project):
    summary = inspect_reports(reports, facts)
    summary["issues"].extend(errors)
    native = receipt["commands"].get("NATIVE")
    require(type(receipt["native_invocations"]) is int and receipt["native_invocations"] in (0, 1), "saved native invocation count type/value changed")
    if native:
        require(type(native["timed_out"]) is bool and (native["return_code"] is None or type(native["return_code"]) is int),
                "invalid saved native return/timeout type")
        logs = b"\n".join(inputs.read_bounded(project, native[k], 64 * 1024 * 1024) for k in ("stdout", "stderr"))
        warnings = bool(re.search(rb"\b(?:warning|fatal|error)\b|G4Exception", logs, re.I))
        require(receipt["native_warning_or_error_log"] is warnings, "saved warning classification changed")
    if native and native["timed_out"]:
        summary["status"] = "timed_out_partial"
        summary["scoped_acceptance"] = False
    elif receipt["error"] or errors or not native or native["return_code"] != 0:
        summary["scoped_acceptance"] = False
        if summary["status"] == "complete_native_audit":
            summary["status"] = "failed_native_audit"
    if receipt["native_warning_or_error_log"] and summary["status"] == "complete_native_audit":
        summary["status"] = "completed_with_native_warnings"
        summary["scoped_acceptance"] = False
    return summary


def verify(project=ROOT):
    """Read completed/partial artifacts only; never call a subprocess or solver."""
    facts = expected(project)
    receipt = load(project, BASE + "/CONTROL-RUN.json")
    require(receipt.get("kind") == "m11f_control_run_v1" and receipt.get("verification_scope") == SCOPE, "unsupported saved receipt")
    require(frozen_sources(project) == receipt["source_records"], "saved source identity changed")
    reports, errors = saved_artifacts(project, receipt)
    summary = interpret_saved(receipt, reports, errors, facts, project)
    require(summary == receipt["inspection"], "saved receipt interpretation/metadata changed")
    return receipt


def reinspect(project=ROOT, receipt_sha256=None):
    """Reinterpret exact saved observations; retain the original receipt unchanged."""
    require(type(receipt_sha256) is str and re.fullmatch(r"[0-9a-f]{64}", receipt_sha256), "reinspection requires external exact receipt SHA256")
    original_pin = pin(project, BASE + "/CONTROL-RUN.json")
    require(original_pin["sha256"] == receipt_sha256, "original receipt SHA256 mismatch")
    receipt = load(project, BASE + "/CONTROL-RUN.json")
    require(receipt.get("kind") == "m11f_control_run_v1" and receipt.get("verification_scope") == SCOPE, "unsupported saved receipt")
    freeze = load(project, BASE + "/SOURCE-FREEZE.json")
    require(freeze.get("kind") == "m11f_source_freeze_v1" and type(freeze.get("source_records")) is dict and
            set(freeze["source_records"]) == set(SOURCES) and freeze["source_records"] == receipt["source_records"],
            "historical source-freeze identity mismatch")
    for ref, record in freeze["source_records"].items():
        require(pin(project, BASE + "/source-frozen/" + ref) == record, "historical source snapshot changed: " + ref)
    for ref in ("tools/native_cryostat_audit/CMakeLists.txt", "tools/native_cryostat_audit/audit.cc", EXPECTED):
        require(pin(project, ref) == freeze["source_records"][ref], "reinspection cannot change native/expected identity: " + ref)
    facts = expected(project)
    reports, errors = saved_artifacts(project, receipt)
    summary = interpret_saved(receipt, reports, errors, facts, project)
    return {"kind": "m11f_saved_reinspection_v1", "verification_scope": SCOPE, "status": summary["status"],
            "scoped_acceptance": summary["scoped_acceptance"], "original_receipt_record": original_pin,
            "original_inspection": receipt["inspection"], "inspection": summary,
            "historical_freeze_record": pin(project, BASE + "/SOURCE-FREEZE.json"),
            "historical_source_records": freeze["source_records"],
            "verifier_source_records": {ref: pin(project, ref) for ref in SOURCES},
            "checkpoint_records": receipt["checkpoint_records"], "native_warning_or_error_log": receipt["native_warning_or_error_log"],
            "original_native_invocations": receipt["native_invocations"], "native_invocations_this_call": 0,
            "experimental_acceptance": "not_established", "adapter_eligibility": "unchanged_candidate_input_only"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("check", "freeze", "run", "verify", "reinspect"))
    parser.add_argument("--receipt-sha256", help="externally recorded exact original run digest; required for reinspect")
    parser.add_argument("--json", action="store_true", help="compact summary; raw reports remain local")
    args = parser.parse_args(argv)
    try:
        require(args.operation == "reinspect" or args.receipt_sha256 is None, "receipt SHA256 is only for reinspect")
        if args.operation in ("check", "freeze"):
            expected()
            if args.operation == "freeze":
                freeze()
            result = {"status": "source_snapshot_created" if args.operation == "freeze" else "expected_metadata_verified", "verification_scope": SCOPE,
                      "native_invocations": 0, "scoped_acceptance": False, "experimental_acceptance": "not_established"}
            code = 0
        elif args.operation == "reinspect":
            result = reinspect(receipt_sha256=args.receipt_sha256)
            code = 0 if result["scoped_acceptance"] else 1
        else:
            receipt = run() if args.operation == "run" else verify()
            result = {"status": receipt["inspection"]["status"], "verification_scope": SCOPE,
                      "scoped_acceptance": receipt["inspection"]["scoped_acceptance"], "stages": receipt["inspection"]["stages"],
                      "gps_positions": receipt["inspection"]["gps_positions"], "native_invocations": receipt["native_invocations"],
                      "experimental_acceptance": "not_established", "adapter_eligibility": "unchanged_candidate_input_only"}
            code = 0 if result["scoped_acceptance"] else 1
    except (AuditError, OSError, KeyError, TypeError, ValueError) as error:
        result = {"status": "failed_control_verification", "verification_scope": SCOPE, "error": str(error), "scoped_acceptance": False,
                  "experimental_acceptance": "not_established", "adapter_eligibility": "unchanged_candidate_input_only"}
        code = 1
    label = "Saved-data reinspection (native calls=0): " if args.operation == "reinspect" else "Bounded native structure/source-position inspection: "
    print(json.dumps(result, separators=(",", ":")) if args.json else
          label + result["status"] +
          "; scoped acceptance=" + str(result["scoped_acceptance"]) +
          "; adapter remains candidate; experimental acceptance not established.")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
