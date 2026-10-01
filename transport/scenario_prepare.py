"""Finite M11a source-instance preparation. No radiation, charge or readout runner."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import subprocess
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
PINNED_MODELS = {
    "AK02": "793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
    "SAP22": "614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3",
}
KIND = "scenario_source_prepared_v1"
UNITS = {"length": "mm", "time": "ns", "energy": "keV", "angle": "deg",
         "potential": "V", "temperature": "K"}
ROTATION = [[1, 0, 0], [0, 0, 1], [0, -1, 0]]
POSES = {"nominal": [0, 37.073, 0.290], "plus5mm": [0, 42.073, 0.290]}
EXPORTER_SHA256 = "87b510882ed3f07b610895fddc93d7c3a4d16e8cf2b5a22d2d7994b31164266e"
PINNED_INPUTS = {
    "transport/cryostat_nominal.json": "9cad951c14213ac64d1e0c83c6ee44e7f4b9990d80979fd5bae35797daaf0edb",
    "transport/cryostat-source.json": "5967d5d0f8500a40f704bf653be2dc1a0f69e77239f643a8f7140533c9201e2a",
    "transport/handoff.py": "5eaf9c41852b4f4b45b3c36f78314b9fba28c39fcc4155694e8b6459375df193",
    "transport/cs137.py": "de1c276a304dad5ffa1338732e96719b22ad115e4dd8344d04ae5a91c934224d",
    "transport/cryostat_export.cc": "af44c9893e4576151511b185989ff1bc88431b36261d2d3b2607640d335e767b",
    "transport/pixi.toml": "87991463283a4f00b7e8a2758d9019c39ebe0fcad1387e87e500ed500f0638dd",
    "transport/pixi.lock": "c212a7f7e78bb7af4687bbbc7322659975961e62c3ea71a6f325e65e554b56be",
    "transport/CMakeLists.txt": "9ea59c94d38667c65a61644164ddc245f012996a9833efc830fb82aa717f8ab1",
    "models/catalog.json": "ac5edd4c976a37cfcc80a8e507ac9347246a942ac843ed2ecc683079f220653b",
    "models/AK02.yaml": PINNED_MODELS["AK02"], "models/SAP22.yaml": PINNED_MODELS["SAP22"],
    "models/ADLChargeDriftModel/drift_velocity_config.yaml": "642a2bd0df1dabd9da7c71d15950e8b84f491babfd4b4fb63abdb82162f97ce6",
    "simulation/native_readout_profile.json": "7556e6e77d6c21e76e1a4eabb69b2b26875517252c083c88b6eb6a80502ef6e6",
}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def json_text(value):
    return json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n"


def native_helpers():
    """Only prepare imports the existing numerical/export libraries."""
    global h, c
    import handoff as h
    import cs137 as c
    return h, c


def asset_records():
    """Adapter-owned semantics: a matching user-provided hash is insufficient."""
    records = {
        "lbnl_modular_nominal_v1": {
            "schema_version": 1, "kind": "cryostat_asset", "id": "lbnl_modular_nominal_v1", "version": 1,
            "geometry_ref": "transport/cryostat_nominal.json",
            "geometry_sha256": PINNED_INPUTS["transport/cryostat_nominal.json"],
            "upstream_manifest_ref": "transport/cryostat-source.json",
            "upstream_manifest_sha256": PINNED_INPUTS["transport/cryostat-source.json"],
            "upstream_entry": "stage.tg", "upstream_chain": ["stage.tg", "shield.tg", "chamber.tg"],
            "capsule_axis_global": [0, 1, 0], "capsule_material": "G4_Al",
            "fill_material": "G4_POLYETHYLENE", "spacer_material": "boron_nitride",
            "supported_stages": ["check", "prepare"],
            "scope": "Nominal engineering geometry; not surveyed/as-built; original upstream bytes stay private.",
        },
        "cs137_point_decay_v1": {
            "schema_version": 1, "kind": "source_asset", "id": "cs137_point_decay_v1", "version": 1,
            "particle": "ion", "pdg": 1000551370, "Z": 55, "A": 137,
            "kinetic_energy_keV": 0, "distribution": "point", "angular_policy": "radioactive_decay",
            "direction_global": None, "clock_policy": "remage_initial_decay_secondaries_zero",
            "time_ns": 0, "particles_per_primary": 1, "daughter_lifetime_limit_ns": -1,
            "normalization": "per initial Cs137 decay; conditional isolated windows, not activity/live time",
        },
        "mono_gamma_662_axis_v1": {
            "schema_version": 1, "kind": "source_asset", "id": "mono_gamma_662_axis_v1", "version": 1,
            "particle": "gamma", "pdg": 22, "kinetic_energy_keV": 662, "distribution": "point",
            "angular_policy": "fixed_global_direction", "direction_global": [0, -1, 0],
            "clock_policy": "synthetic_primary_time_zero", "time_ns": 0, "particles_per_primary": 1,
            "daughter_lifetime_limit_ns": None,
            "normalization": "per one synthetic 662 keV incident gamma; no decay/activity normalization",
        },
    }
    for model, bias in (("AK02", 500), ("SAP22", 700)):
        records[model] = {
            "schema_version": 1, "kind": "detector_asset", "id": model, "version": 1,
            "model_ref": "models/" + model + ".yaml", "model_sha256": PINNED_MODELS[model],
            "catalog_ref": "models/catalog.json", "catalog_sha256": PINNED_INPUTS["models/catalog.json"],
            "includes_sha256": {} if model == "AK02" else {
                "models/ADLChargeDriftModel/drift_velocity_config.yaml":
                    PINNED_INPUTS["models/ADLChargeDriftModel/drift_velocity_config.yaml"]},
            "material": "HPGe", "temperature_K": 78,
            "contacts": [{"id": 1, "potential_V": 0}, {"id": 2, "potential_V": bias}],
            "readout_contact_id": 1, "readout_profile_ref": "simulation/native_readout_profile.json",
            "readout_profile_sha256": PINNED_INPUTS["simulation/native_readout_profile.json"],
            "scope": "Original SSD snapshot; preparation computes no fields or carrier response; no 77 K override.",
        }
    return records


def asset_ref(asset_id):
    return "scenarios/assets/" + asset_id + ".json"


def json_snapshot(path):
    """Parse and digest the same bytes, never a second mutable file read."""
    data = Path(path).read_bytes()
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, "duplicate JSON key: " + key)
            result[key] = value
        return result
    def constant(value):
        raise ValueError("nonfinite JSON number: " + value)
    document = json.loads(data.decode("utf-8"), object_pairs_hook=pairs, parse_constant=constant)
    return document, hashlib.sha256(data).hexdigest()


def strict_load(path):
    return json_snapshot(path)[0]


def project_file(path):
    path = Path(os.path.abspath(path))
    require(path.is_relative_to(ROOT) and path != ROOT, "input must be inside project")
    current = ROOT
    require(not current.is_symlink() and not getattr(current, "is_junction", lambda: False)(), "linked project root refused")
    for part in path.relative_to(ROOT).parts:
        current /= part
        require(not current.is_symlink() and not getattr(current, "is_junction", lambda: False)(), "linked input refused")
    require(path.resolve() == path and path.is_file(), "missing/unsafe input file")
    return path


def exact(actual, expected, message):
    # JSON serialization also distinguishes true from 1 and refuses NaN/Infinity.
    require(json_text(actual) == json_text(expected), message)


def check(config):
    """Pure file/configuration resolution: no outputs, subprocess or runtime lookup."""
    config = project_file(config)
    instance, config_digest = json_snapshot(config)
    require(type(instance) is dict and set(instance) == {
        "schema_version", "kind", "cryostat", "detector", "source", "source_pose",
        "primary_count", "seed", "units"}, "unsupported instance keys")
    exact(instance["schema_version"], 1, "unsupported instance version")
    exact(instance["kind"], "source_instance_v1", "unsupported instance kind")
    exact(instance["units"], UNITS, "unsupported units")
    require(type(instance["primary_count"]) is int and instance["primary_count"] == 20, "count must be 20")
    require(type(instance["seed"]) is int and instance["seed"] == 26092631, "seed must be 26092631")
    require(type(instance["source_pose"]) is str and instance["source_pose"] in POSES, "unsupported source pose")
    records, selected, hashes = asset_records(), {}, {}
    allowed = {"cryostat": ("lbnl_modular_nominal_v1",), "detector": ("AK02", "SAP22"),
               "source": ("cs137_point_decay_v1", "mono_gamma_662_axis_v1")}
    for role, ids in allowed.items():
        reference = instance[role]
        require(type(reference) is dict and set(reference) == {"id", "version", "ref", "sha256"}, "unsupported asset reference keys")
        aid = reference["id"]
        require(type(aid) is str and aid in ids, "unsupported " + role + " ID")
        exact(reference["version"], 1, "unsupported asset version")
        exact(reference["ref"], asset_ref(aid), "unsupported/unsafe asset ref")
        p = project_file(ROOT / reference["ref"])
        require(type(reference["sha256"]) is str and re.fullmatch(r"[0-9a-f]{64}", reference["sha256"]), "invalid asset SHA256")
        document, asset_digest = json_snapshot(p)
        require(asset_digest == reference["sha256"], "asset byte hash mismatch")
        exact(document, records[aid], "asset semantics differ from supported registry: " + aid)
        selected[role], hashes[reference["ref"]] = records[aid], asset_digest
    nominal_ref = "transport/cryostat_nominal.json"
    scenario, nominal_digest = json_snapshot(project_file(ROOT / nominal_ref))
    require(nominal_digest == PINNED_INPUTS[nominal_ref], "pinned input changed: " + nominal_ref)
    for name, digest in PINNED_INPUTS.items():
        if name == nominal_ref:
            continue  # Its parsed snapshot and pin were checked together above.
        require(sha256(project_file(ROOT / name)) == digest, "pinned input changed: " + name)
    # Check binds exact reviewed YAML bytes and metadata; it does not parse/solve YAML.
    # Prepare independently parses the model through the existing locked runtime.
    centre = POSES[instance["source_pose"]]
    plan = {"kind": "source_instance_plan_v1", "schema_version": 1,
            "supported_stages": ["check", "prepare"], "instance": instance,
            "assets": selected, "source_position_global_mm": centre,
            "source_pose_status": "candidate until this preparation's native checks pass",
            "coordinate_transform": scenario["coordinate_transform"],
            "nominal_geometry": scenario,
            "capsule_rotation_local_to_global": ROTATION,
            "model_check": "exact pinned bytes/reviewed metadata; independent YAML parse occurs only in prepare",
            "input_sha256": {**PINNED_INPUTS, **hashes,
                              config.relative_to(ROOT).as_posix(): config_digest},
            "stages": {"geometry": "not_executed", "source_macro": "not_prepared",
                       "transport": "not_executed", "charge": "not_executed", "readout": "not_executed"}}
    return plan


# The upstream assembly has four screwBar placements with the same original path.
# The pair (original_path, copy_number), together with unique renamed name, identifies them.
VACUUM = "/RmP124/endCap/hollow/shield/vacuum"
LEDGER = [
    ("ledger_0_PV", "/RmP124", 0, "G4_AIR"),
    ("ledger_1", "/RmP124/flange", -10, "G4_Al"),
    ("ledger_2", "/RmP124/endCap", -11, "G4_Al"),
    ("ledger_3", "/RmP124/endCap/hollow", -12, "G4_Galactic"),
    ("ledger_4", "/RmP124/endCap/hollow/shield", -21, "G4_Al"),
    ("ledger_5", VACUUM, -20, "G4_Galactic"),
    *[("ledger_" + str(i), VACUUM + "/" + name, number, material)
      for i, name, number, material in [
          (6, "stage", -30, "G4_Al"), (7, "backStage", -31, "G4_Al"),
          (8, "screwBar", -32, "G4_Al"), (9, "screwBar", -33, "G4_Al"),
          (10, "screwBar", -34, "G4_Al"), (11, "screwBar", -35, "G4_Al"),
          (12, "BNblock", -36, "boron_nitride"), (13, "InBelow", -37, "G4_In"),
          (14, "CuPlate", -38, "G4_Cu"), (15, "InAbove", -39, "G4_In")]],
    ("germanium", VACUUM + "/germanium", 1, "G4_Ge"),
    ("ledger_17", VACUUM + "/nominal_spacer", 1, "boron_nitride"),
    ("ledger_18", "/RmP124/nominal_capsule", 1, "G4_Al"),
    ("ledger_19", "/RmP124/nominal_capsule/nominal_source_fill", 1, "G4_POLYETHYLENE"),
]
MATERIALS = {
    "G4_AIR": (0.00120479, {"C": 0.000124000124000124, "N": 0.75526775526775525,
                           "O": 0.23178123178123175, "Ar": 0.012827012827012825}),
    "G4_Al": (2.699, {"Al": 1}), "G4_Galactic": (1e-25, {"H": 1}),
    "boron_nitride": (1.9, {"B": 0.43561567815896374, "N": 0.56438432184103626}),
    "G4_In": (7.31, {"In": 1}), "G4_Cu": (8.96, {"Cu": 1}), "G4_Ge": (5.323, {"Ge": 1}),
    "G4_POLYETHYLENE": (0.94, {"C": 0.85628171225519822, "H": 0.14371828774480183}),
}


def number(value):
    h.require(type(value) in (int, float) and math.isfinite(value), "required finite number")
    return value


def vector(value, size):
    h.require(type(value) is list and len(value) == size, "invalid numeric vector")
    return [number(x) for x in value]


def placement(volume, translation, rotation):
    h.require(h.np.allclose(volume["translation_global_mm"], translation, rtol=0, atol=1e-10), "placement translation mismatch")
    h.require(h.np.allclose(volume["rotation_local_to_global"], rotation, rtol=0, atol=1e-12), "placement rotation mismatch")


def require_source_inside_fill_mm(point_global_mm, fill):
    vector(point_global_mm, 3)
    # Both operands are mm. h.to_local instead accepts global metres.
    local_point = (h.np.asarray(point_global_mm) - h.np.asarray(fill["translation_global_mm"])) @ h.np.asarray(fill["rotation_local_to_global"])
    # Conservatively refuse a boundary rounded inward by the global subtraction.
    h.require(math.hypot(local_point[0], local_point[1]) < 2.9 - 1e-12 and abs(local_point[2]) < 0.4 - 1e-12,
              "source point is not strictly inside fill")


def validate_report(report, plan, probes):
    h.require(type(report) is dict and set(report) == {"schema_version", "geant4_version_number", "overlap_seed",
        "overlap_samples", "source_inside_fill", "crystal_volume_mm3", "volumes", "probes", "overlaps_passed"}, "unsupported native report keys")
    for name, expected in (("schema_version", 1), ("geant4_version_number", 1132),
                           ("overlap_seed", 26092632), ("overlap_samples", 10000)):
        h.require(type(report[name]) is int and report[name] == expected, "native report " + name + " mismatch")
    h.require(report["source_inside_fill"] is True and report["overlaps_passed"] is True, "native containment/overlap check failed")
    h.require(math.isclose(number(report["crystal_volume_mm3"]), h.reference_volume(plan["assets"]["detector"]["id"]), rel_tol=1e-10), "solid volume mismatch")
    h.require(type(report["probes"]) is list and len(report["probes"]) == len(probes), "native probe count mismatch")
    for i, (found, expected) in enumerate(zip(report["probes"], probes)):
        h.require(type(found) is dict and set(found) == {"index", "classification"}
                  and type(found["index"]) is int and found["index"] == i
                  and found["classification"] == expected["expected"], "native Inside probe mismatch")
    volumes = report["volumes"]
    h.require(type(volumes) is list and len(volumes) == len(LEDGER), "native volume count mismatch")
    names, pairs = set(), set()
    for found, expected in zip(volumes, LEDGER):
        h.require(type(found) is dict and set(found) == {"name", "original_path", "copy_number", "material",
            "density_g_cm3", "elements", "translation_global_mm", "rotation_local_to_global", "overlap"}, "unsupported volume keys")
        name, path, copy_number, material = expected
        h.require(type(found["copy_number"]) is int and (found["name"], found["original_path"], found["copy_number"], found["material"]) == expected,
                  "native volume/material/copy/ancestor mapping mismatch")
        h.require(name not in names and (path, copy_number) not in pairs, "duplicate volume mapping")
        names.add(name); pairs.add((path, copy_number))
        h.require(found["overlap"] is False, "native volume overlap flag failed")
        density, fractions = MATERIALS[material]
        h.require(math.isclose(number(found["density_g_cm3"]), density, rel_tol=1e-12), "native material density mismatch")
        h.require(type(found["elements"]) is list and len(found["elements"]) == len(fractions), "native element count mismatch")
        seen = set()
        for element in found["elements"]:
            h.require(type(element) is dict and set(element) == {"name", "mass_fraction"}
                      and type(element["name"]) is str and element["name"] in fractions and element["name"] not in seen, "native element mapping mismatch")
            seen.add(element["name"])
            h.require(math.isclose(number(element["mass_fraction"]), fractions[element["name"]], rel_tol=1e-12), "native element fraction mismatch")
        vector(found["translation_global_mm"], 3)
        h.require(type(found["rotation_local_to_global"]) is list and len(found["rotation_local_to_global"]) == 3, "invalid rotation")
        for row in found["rotation_local_to_global"]:
            vector(row, 3)
        h.validate_transform({"definition": h.TRANSFORM["definition"],
            "translation_global_mm": found["translation_global_mm"], "rotation_local_to_global": found["rotation_local_to_global"]})
    placement(volumes[0], [0, 0, 0], h.TRANSFORM["rotation_local_to_global"])
    placement(volumes[5], [0, 1.473, -3.710], h.TRANSFORM["rotation_local_to_global"])
    placement(volumes[16], plan["coordinate_transform"]["translation_global_mm"], ROTATION)
    for volume in volumes[18:20]:
        placement(volume, plan["source_position_global_mm"], ROTATION)
    require_source_inside_fill_mm(plan["source_position_global_mm"], volumes[19])


DECAY_ONLY = ["# Nominal curved-cap top; conditional decay clock, not activity clock.",
    "/process/had/rdm/thresholdForVeryLongDecayTime 1e27 ns",
    "/RMG/Processes/Stepping/ResetInitialDecayTime true",
    "/RMG/Processes/Stepping/DaughterNucleusMaxLifetime -1 ns",
    "/RMG/Processes/Stepping/LargeGlobalTimeUncertaintyWarning 0.001 ns"]


def source_macro(report, plan):
    source = plan["source_position_global_mm"]
    original = c.macro_text(report, 20, source)
    if plan["assets"]["source"]["id"] == "cs137_point_decay_v1":
        return original
    lines = original.splitlines()
    boundary = "/RMG/Generator/Select GPS"
    h.require(lines.count(boundary) == 1, "unexpected generator boundary")
    split = lines.index(boundary)
    centre = "/gps/pos/centre " + " ".join(format(v, ".17g") for v in source) + " mm"
    exact(lines[split:], [boundary, "/gps/particle ion", "/gps/ion 55 137", "/gps/energy 0 eV",
                         "/gps/pos/type Point", centre, "/gps/time 0 ns", "/gps/number 1", "/run/beamOn 20"], "unexpected legacy Cs137 generator suffix")
    for line in DECAY_ONLY:
        h.require(lines[:split].count(line) == 1, "unexpected legacy decay-only prefix")
    prefix = [line for line in lines[:split] if line not in DECAY_ONLY]
    h.require(not any(line.startswith(("/gps/", "/RMG/Generator/")) for line in prefix), "unexpected source command in common prefix")
    return "\n".join(["# Synthetic one-gamma primary; fixed global -y, time zero; no activity clock.",
        *prefix, boundary, "/gps/particle gamma", "/gps/pos/type Point", centre,
        "/gps/direction 0 -1 0", "/gps/ene/type Mono", "/gps/ene/mono 662 keV",
        "/gps/time 0 ns", "/gps/number 1", "/run/beamOn 20"]) + "\n"


def frozen_inventory(config, exporter):
    files = {**c.source_hashes(), **{name: h.sha256(project_file(h.ROOT / name)) for name in PINNED_INPUTS}}
    files = {("transport/" + name if "/" not in name else name): digest for name, digest in files.items()}
    for name in ["transport/scenario_prepare.py", "transport/Prepare.cmd", "transport/prepare.sh",
                 *(asset_ref(aid) for aid in asset_records())]:
        files[name] = h.sha256(project_file(h.ROOT / name))
    files[project_file(config).relative_to(h.ROOT).as_posix()] = h.sha256(config)
    files[exporter.relative_to(h.ROOT).as_posix()] = h.sha256(exporter)
    files.update({".local/transport/LBNL/" + name: digest for name, digest in c.upstream_hashes().items()})
    return files


def prepare(config, output, exporter):
    start = time.perf_counter()
    plan = check(config)
    native_helpers()
    doc, points = h.load_model(plan["assets"]["detector"]["id"])
    exact(doc["detectors"][0]["semiconductor"]["temperature"], 78, "model temperature mismatch")
    exact([{"id": contact["id"], "potential_V": contact["potential"]}
           for contact in doc["detectors"][0]["contacts"]], plan["assets"]["detector"]["contacts"], "model contact mismatch")
    plan["contour_rz_mm"] = points
    output, exporter = h.local_path(output), h.local_path(exporter)
    h.require(not output.exists(), "output exists; choose a fresh root")
    h.require(exporter.is_file() and exporter.stat().st_size == 83872 and h.sha256(exporter) == EXPORTER_SHA256,
              "missing/changed existing exporter; no build/install/fallback is permitted")
    frozen = frozen_inventory(config, exporter)
    h.require(all(frozen.get(name) == digest for name, digest in plan["input_sha256"].items()),
              "checked plan input changed before preparation inventory")
    scenario = plan["nominal_geometry"]
    probes = h.probe_points(plan["contour_rz_mm"])
    output.mkdir(parents=True, exist_ok=False)
    status = {"status": "failed", "stage": "geometry_preparation", "kind": KIND}
    try:
        h.local_path(output)
        h.write_new(output / "canonical.gdml", h.gdml_text(plan["contour_rz_mm"]))
        h.write_new(output / "probe-points.txt", "".join(" ".join(format(x, ".17g") for x in p["position_mm"]) + "\n" for p in probes))
        h.write_new(output / "resolved-instance.json", h.json_text(plan))
        sp, cap = scenario["spacer"], scenario["capsule"]
        parameters = [*scenario["coordinate_transform"]["translation_global_mm"],
            *scenario["expected_vacuum_global_translation_mm"], *sp["vacuum_centre_mm"], sp["radius_mm"],
            sp["thickness_mm"], *plan["source_position_global_mm"], cap["radius_mm"], cap["thickness_mm"], cap["wall_mm"], 10000]
        h.write_new(output / "parameters.txt", " ".join(format(v, ".17g") for v in parameters) + "\n")
        generated_inputs = {p.name: h.sha256(p) for p in output.iterdir() if p.is_file()}
        h.require(frozen_inventory(config, exporter) == frozen, "input changed before exporter launch")
        command = [str(exporter), str(h.ROOT / ".local/transport/LBNL/stage.tg"),
            *(str(output / p) for p in ("canonical.gdml", "probe-points.txt", "parameters.txt", "geometry.gdml", "geometry-report.json"))]
        status["command"] = command
        with (output / "geometry.log").open("x", encoding="utf-8") as log:
            native_start = time.perf_counter()
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False, shell=False)
            status["native_geometry_wall_s"] = time.perf_counter() - native_start
        status["returncode"] = result.returncode
        h.require(result.returncode == 0, "native import/check failed; retained log/report")
        h.require(not re.search(r"\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read|cryostat_export:",
            (output / "geometry.log").read_text(errors="replace"), re.I), "native diagnostic failure; retained log/report")
        report = strict_load(h.local_path(output / "geometry-report.json"))
        h.require(h.local_path(output / "geometry.gdml").is_file(), "native geometry missing")
        validate_report(report, plan, probes)
        h.write_new(output / "run.mac", source_macro(report, plan))
        h.require(all(h.sha256(h.local_path(output / name)) == digest for name, digest in generated_inputs.items()), "generated input changed during exporter")
        h.require(frozen_inventory(config, exporter) == frozen, "frozen source/input changed; retain failed derivative")
        meta = {"kind": KIND, "schema_version": 1, "status": "prepared",
            "model_id": plan["assets"]["detector"]["id"], "instance": plan["instance"], "assets": plan["assets"],
            "source_position_global_mm": plan["source_position_global_mm"],
            "source_pose_status": "native geometry checked for this preparation; nominal engineering pose",
            "coordinate_transform": plan["coordinate_transform"], "contour_rz_mm": plan["contour_rz_mm"],
            "stages": {"geometry": "geometry_checked", "source_macro": "source_macro_prepared",
                       "transport": "transport_not_executed", "charge": "charge_not_executed", "readout": "readout_not_executed"},
            "source_sha256": frozen, "legacy_source_sha256": c.source_hashes(), "upstream_sha256": c.upstream_hashes(),
            "exporter_sha256": EXPORTER_SHA256, "versions": {**h.python_versions(),
                "geant4_version_number": report["geant4_version_number"]},
            "overlap_seed": 26092632, "overlap_samples": 10000,
            "grouping_policy": {**c.POLICY, "horizon_ns": scenario["group_horizon_ns"]},
            "energy_closure": None, "activity_Bq": None,
            "assumptions": [scenario["status"], "baseline nominal top reference: " + scenario["top_assumption"],
                "selected pose " + plan["instance"]["source_pose"] + "; plus5mm is 5 mm beyond the nominal capsule/source centre along global +y",
                "source point and capsule/fill move together; capsule axis global +y", "overlap sampling is not geometry convergence",
                "planned count/seed/macro are inputs; no emitted event census or raw quantities exist"],
            "unknowns": scenario["unknowns"], "omitted": scenario["omitted"],
            "unscored_volumes": [{"name": "ledger_0_PV", "material": "G4_AIR",
                "reason": "world is unscored; world/escape/neutrino energy closure not established"}],
            "material_tables": {"stp/" + v["name"]: v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"},
            "files_sha256": {p.name: h.sha256(h.local_path(p)) for p in output.iterdir() if p.is_file()},
            "native_geometry_wall_s": status["native_geometry_wall_s"]}
        h.publish_json(output / "prepared.json", meta)
        status["status"] = "complete"
        return meta
    except Exception as error:
        status["error"] = str(error)
        raise
    finally:
        status["preparation_wall_s"] = time.perf_counter() - start
        h.publish_json(output / "prepare-receipt.json", status)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "prepare"):
        item = sub.add_parser(name)
        item.add_argument("--config", required=True)
        if name == "prepare":
            item.add_argument("--output", required=True)
            item.add_argument("--exporter", required=True)
    args = parser.parse_args()
    result = check(args.config) if args.command == "check" else prepare(args.config, args.output, args.exporter)
    print(json_text(result), end="")


if __name__ == "__main__":
    main()
