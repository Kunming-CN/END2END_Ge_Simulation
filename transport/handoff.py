"""Bare canonical HPGe transport and flat remage LH5 -> small JSON v1 fixtures.

No charge response, event selection, clustering, or experimental source model.
Run through transport/run.sh in the existing locked Linux environment.
"""
import argparse
import hashlib
import importlib.metadata
import json
import math
import os
from pathlib import Path
import platform
import re
import subprocess
import xml.etree.ElementTree as ET

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PINNED = {
    "AK02": "793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
    "SAP22": "614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3",
}
TRANSFORM = {
    "rotation_local_to_global": [[1, 0, 0], [0, 1, 0], [0, 0, 1]],
    "translation_global_mm": [0, 0, 0],
    "definition": "x_global_mm=R*x_local_mm+t",
}
BOUNDARY_MM = 1e-6
TABLE = "stp/germanium"
SCOPE = "Bare canonical semiconductor; synthetic side-on monoenergetic gamma interface test"
OMITTED = ["cryostat", "holder/support", "experimental source and encapsulation",
           "zero-thickness outer electrodes", "finite point-contact electrode overlay"]


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


def local_path(path):
    """Reject links/junctions even when their target happens to be within .local."""
    path = Path(os.path.abspath(path))
    base = ROOT / ".local"
    require(path != base and path.is_relative_to(base), "output must be below project .local")
    require(not base.is_symlink() and not getattr(base, "is_junction", lambda: False)(),
            "symlink/junction output root refused")
    current = base
    for name in path.relative_to(base).parts:
        current /= name
        require(not current.is_symlink() and not getattr(current, "is_junction", lambda: False)(),
                "symlink/junction output path refused")
    require(path.resolve().is_relative_to(base.resolve()) and base.resolve() == base,
            "resolved output escapes project .local")
    return path


def write_new(path, text):
    path = local_path(path)
    with path.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)


def publish_json(path, value):
    """Validate/serialize first; link a complete sibling into a never-replaced final name.

    A failed write leaves only .partial evidence. Hard-link publication is atomic and
    no-clobber on the supported filesystem; unsupported filesystems fail visibly.
    """
    text = json_text(value)
    path = local_path(path)
    require(not path.exists(), "final output already exists")
    partial = local_path(path.with_name(path.name + ".partial"))
    with partial.open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    os.link(partial, path)
    partial.unlink()


def numeric(value):
    require(type(value) in (int, float) and math.isfinite(value), "expected finite numeric YAML value")
    return float(value)


def contour_from_document(doc):
    require(doc["units"] == {"length": "mm", "angle": "deg", "potential": "V", "temperature": "K"},
            "unsupported YAML units")
    require(doc["medium"] == "vacuum" and doc["grid"]["coordinates"] == "cylindrical",
            "unsupported medium or coordinates")
    require(len(doc["detectors"]) == 1, "exactly one detector required")
    semiconductor = doc["detectors"][0]["semiconductor"]
    require(semiconductor["material"] == "HPGe", "only HPGe is supported")
    geometry = semiconductor["geometry"]
    require(set(geometry) == {"polycone"} and set(geometry["polycone"]) == {"r", "z"},
            "only untransformed full-azimuth r-z contour polycone is supported")
    r, z = geometry["polycone"]["r"], geometry["polycone"]["z"]
    require(len(r) == len(z) and len(r) >= 4, "invalid contour lengths")
    points = [(numeric(a), numeric(b)) for a, b in zip(r, z)]
    validate_contour(points)
    return points


def validate_contour(points):
    require(points[0] == points[-1], "canonical contour must be explicitly closed")
    require(all(r >= 0 and math.isfinite(r) and math.isfinite(z) for r, z in points),
            "invalid contour coordinate")
    require(len(set(points[:-1])) == len(points) - 1, "repeated contour vertex")
    # Pinned inputs are simple orthogonal contours. Refuse unreviewed slanted/CSG shapes.
    for a, b in zip(points, points[1:]):
        require((a[0] == b[0]) != (a[1] == b[1]), "only nonzero orthogonal contour edges supported")
    edges = list(zip(points, points[1:]))
    for i, (a, b) in enumerate(edges):
        for j, (c, d) in enumerate(edges):
            if j <= i + 1 or (i == 0 and j == len(edges) - 1):
                continue
            overlaps = all(max(min(a[k], b[k]), min(c[k], d[k])) <=
                           min(max(a[k], b[k]), max(c[k], d[k])) for k in (0, 1))
            require(not overlaps, "self-intersecting/touching contour")
    require(revolved_volume(points) > 0, "degenerate contour")


def polygon_area(points):
    return abs(math.fsum(a[0] * b[1] - b[0] * a[1] for a, b in zip(points, points[1:]))) / 2


def revolved_volume(points):
    """Exact first radial moment of a polygon, times 2*pi; mm^3."""
    return abs(math.pi / 3 * math.fsum(
        (a[0] + b[0]) * (a[0] * b[1] - b[0] * a[1]) for a, b in zip(points, points[1:])))


def reference_volume(model_id):
    """Independent cylinder-minus-recess-minus-annular-groove formulas (mm^3).

    Deliberately explicit dimensions, not a second traversal of the parsed contour.
    """
    if model_id == "AK02":
        return math.pi * (12.65**2 * 9.4 - 7.8**2 * 2.1 - (7.75**2 - 2.95**2) * 1.5)
    if model_id == "SAP22":
        return math.pi * (12.75**2 * 10 - 8.85**2 * 4.2 - (8.75**2 - 3.85**2) * 3)
    raise ValueError("unsupported model")


def membership(points, xyz, tolerance=BOUNDARY_MM):
    r, z = math.hypot(xyz[0], xyz[1]), float(xyz[2])
    require(all(math.isfinite(float(v)) for v in xyz), "nonfinite point")
    inside = False
    for (ra, za), (rb, zb) in zip(points, points[1:]):
        # r=0 edges are coordinate seams, not a surface of the revolved solid.
        if ra != 0 or rb != 0:
            dr, dz = rb - ra, zb - za
            t = max(0, min(1, ((r - ra) * dr + (z - za) * dz) / (dr * dr + dz * dz)))
            if math.hypot(r - ra - t * dr, z - za - t * dz) <= tolerance:
                return "surface"
        if (za > z) != (zb > z) and r < ra + (z - za) * (rb - ra) / (zb - za):
            inside = not inside
    return "inside" if inside else "outside"


def load_model(model_id):
    require(model_id in PINNED, "supported canonical IDs: AK02, SAP22")
    path = ROOT / "models" / (model_id + ".yaml")
    catalog = json.loads((ROOT / "models/catalog.json").read_text(encoding="utf-8"))
    entries = [d for d in catalog["detectors"] if d["id"] == model_id]
    require(len(entries) == 1, "model catalog entry missing or duplicated")
    entry = entries[0]
    require(sha256(path) == entry["model_sha256"] == PINNED[model_id], "canonical model hash mismatch")
    require(entry["model"] == model_id + ".yaml", "unexpected catalog filename")
    for dependency in entry["dependencies"]:
        dep = (ROOT / "models" / dependency).resolve()
        require(dep.is_relative_to(ROOT / "models"), "dependency escapes models")
        pins = [d["sha256"] for d in catalog["dependencies"] if d["path"] == dependency]
        require(len(pins) == 1 and sha256(dep) == pins[0], "dependency hash mismatch")
    import yaml
    doc = yaml.safe_load(path.read_bytes())
    require(doc["name"] == model_id, "model identity mismatch")
    points = contour_from_document(doc)
    require(math.isclose(revolved_volume(points), reference_volume(model_id), rel_tol=1e-12),
            "independent volume mismatch")
    return doc, points


def validate_transform(transform):
    require(transform.get("definition") == TRANSFORM["definition"], "unknown transform definition")
    rotation = np.asarray(transform["rotation_local_to_global"], dtype=float)
    translation = np.asarray(transform["translation_global_mm"], dtype=float)
    require(rotation.shape == (3, 3) and translation.shape == (3,), "invalid transform shape")
    require(np.isfinite(rotation).all() and np.isfinite(translation).all(), "nonfinite transform")
    require(np.allclose(rotation.T @ rotation, np.eye(3), rtol=0, atol=1e-12)
            and abs(np.linalg.det(rotation) - 1) <= 1e-12, "transform must be a proper rigid rotation")
    return rotation, translation


def to_local(global_m, transform):
    rotation, translation = validate_transform(transform)
    return (np.asarray(global_m) * 1000 - translation) @ rotation


def to_global(local_mm, transform):
    rotation, translation = validate_transform(transform)
    return (np.asarray(local_mm) @ rotation.T + translation) / 1000


def probe_points(points):
    radius = max(r for r, _ in points)
    top = max(z for _, z in points)
    # These base labels are independent geometric assertions for both pinned models.
    probes = [{"name": name, "position_mm": xyz, "expected": label} for name, xyz, label in [
        ("bulk", [10, 0, 5], "inside"), ("axis_bulk", [0, 0, 5], "inside"),
        ("lower_bore", [1, 0, 1], "outside"), ("upper_groove", [5, 0, top - 0.5], "outside"),
        ("outside_radial", [radius + 1, 0, 5], "outside"),
        ("below", [10, 0, -1], "outside"), ("above", [10, 0, top + 1], "outside"),
    ]]
    for i, ((ra, za), (rb, zb)) in enumerate(zip(points, points[1:])):
        if ra == rb == 0:
            continue
        r, z = (ra + rb) / 2, (za + zb) / 2
        length = math.hypot(rb - ra, zb - za)
        nr, nz = -(zb - za) / length, (rb - ra) / length
        for offset in (-1e-5, 0, 1e-5):
            xyz = [r + offset * nr, 0, z + offset * nz]
            probes.append({"name": f"edge_{i}_offset_{offset:g}_mm", "position_mm": xyz,
                           "expected": membership(points, xyz), "surface_offset_mm": offset})
        require(probes[-2]["expected"] == "surface" and
                {probes[-3]["expected"], probes[-1]["expected"]} == {"inside", "outside"},
                "edge offsets must bracket the physical surface")
    for probe in probes:
        require(membership(points, probe["position_mm"]) == probe["expected"], "probe assertion failed")
    return probes


def gdml_text(points):
    root = ET.Element("gdml")
    ET.SubElement(root, "define")
    ET.SubElement(root, "materials")  # G4 NIST materials resolved by the GDML parser.
    solids = ET.SubElement(root, "solids")
    ET.SubElement(solids, "box", name="world_solid", x="200", y="200", z="200", lunit="mm")
    solid = ET.SubElement(solids, "genericPolycone", name="germanium_solid", startphi="0",
                          deltaphi="360", aunit="deg", lunit="mm")
    # GDML closes implicitly. Remove only the duplicate closing point, never sort z.
    for r, z in points[:-1]:
        ET.SubElement(solid, "rzpoint", r=format(r, ".17g"), z=format(z, ".17g"))
    structure = ET.SubElement(root, "structure")
    ge = ET.SubElement(structure, "volume", name="germanium")
    ET.SubElement(ge, "materialref", ref="G4_Ge")
    ET.SubElement(ge, "solidref", ref="germanium_solid")
    world = ET.SubElement(structure, "volume", name="world")
    ET.SubElement(world, "materialref", ref="G4_Galactic")
    ET.SubElement(world, "solidref", ref="world_solid")
    pv = ET.SubElement(world, "physvol", name="germanium", copynumber="0")
    ET.SubElement(pv, "volumeref", ref="germanium")
    ET.SubElement(pv, "position", name="identity_position", unit="mm", x="0", y="0", z="0")
    ET.SubElement(pv, "rotation", name="identity_rotation", unit="deg", x="0", y="0", z="0")
    setup = ET.SubElement(root, "setup", name="Default", version="1.0")
    ET.SubElement(setup, "world", ref="world")
    ET.indent(root)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(root, encoding="unicode") + "\n"


def macro_text(points, events, energy):
    radius = max(r for r, _ in points)
    mid_z = (min(z for _, z in points) + max(z for _, z in points)) / 2
    return f"""# Synthetic interface source; no experimental source activity or apparatus.
/RMG/Geometry/RegisterDetector Germanium germanium 1
/RMG/Output/NtupleUseVolumeName true
/RMG/Output/NtuplePerDetector true
/RMG/Processes/LowEnergyEMPhysics Livermore
/RMG/Processes/HadronicPhysics None
/RMG/Processes/OpticalPhysics false
/run/initialize
/RMG/Processes/DefaultProductionCut 0.1 mm
/RMG/Processes/SensitiveProductionCut 0.01 mm
/RMG/Output/Germanium/StoreSinglePrecisionEnergy false
/RMG/Output/Germanium/StoreSinglePrecisionPosition false
/RMG/Output/Germanium/StoreTrackID true
/RMG/Output/Germanium/StepPositionMode Both
/RMG/Output/Germanium/Cluster/PreClusterOutputs false
/RMG/Output/Germanium/DiscardZeroEnergyHits false
/RMG/Output/Vertex/SkipPrimaryVertexOutput false
/RMG/Output/Vertex/StoreSinglePrecisionPosition false
/RMG/Output/Vertex/StoreSinglePrecisionEnergy false
/RMG/Output/Vertex/StorePrimaryParticleInformation true
/geometry/test/run
/RMG/Generator/Select GPS
/gps/particle gamma
/gps/pos/type Point
/gps/pos/centre {radius + 10:.17g} 0 {mid_z:.17g} mm
/gps/direction -1 0 0
/gps/ene/type Mono
/gps/ene/mono {energy:.17g} keV
/gps/time 0 ns
/gps/number 1
/run/beamOn {events}
"""


def input_bundle(model_id, events, seed, energy):
    require(type(events) is int and 0 < events <= 100000, "events must be an integer in 1..100000")
    require(type(seed) is int and 0 < seed < 2**31, "seed must be an integer in 1..2^31-1")
    energy = numeric(energy)
    require(energy > 0, "primary energy must be positive")
    doc, points = load_model(model_id)
    probes = probe_points(points)
    files = {"geometry.gdml": gdml_text(points), "run.mac": macro_text(points, events, energy),
             "probe-points.txt": "".join(" ".join(format(x, ".17g") for x in p["position_mm"]) + "\n"
                                          for p in probes)}
    meta = {
        "schema_version": 1, "model_id": model_id, "model_sha256": PINNED[model_id],
        "catalog_sha256": sha256(ROOT / "models/catalog.json"),
        "lock_sha256": sha256(ROOT / "transport/pixi.lock"),
        "manifest_sha256": sha256(ROOT / "transport/pixi.toml"),
        "adapter_sha256": sha256(Path(__file__)),
        "primary_count": events, "seed": seed, "energy_keV": energy,
        "coordinate_transform": TRANSFORM, "scope": SCOPE, "omitted_hardware": OMITTED,
        "stored_temperature_K": doc["detectors"][0]["semiconductor"]["temperature"],
        "stored_contact_potentials_V": [c["potential"] for c in doc["detectors"][0]["contacts"]],
        "mass_material": "G4_Ge; entire canonical HPGe volume sensitive, including Li region",
        "physics": {"EM": "Livermore", "default_production_cut_mm": 0.1,
                    "sensitive_production_cut_mm": 0.01, "step_limit": None},
        "contour_rz_mm": points, "analytic_volume_mm3": reference_volume(model_id),
        "polygon_volume_mm3": revolved_volume(points), "probes": probes,
        "boundary_tolerance_mm": BOUNDARY_MM,
        "files_sha256": {name: hashlib.sha256(value.encode()).hexdigest() for name, value in files.items()},
    }
    return files, meta


def prepare(model_id, output, events=100, seed=260925, energy=662):
    output = local_path(output)
    require(not output.exists(), "prepare refuses an existing output directory")
    files, meta = input_bundle(model_id, events, seed, energy)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in files.items():
        write_new(output / name, value)
    publish_json(output / "prepared.json", meta)
    return output


def read_prepared(directory):
    directory = local_path(directory)
    meta = json.loads(local_path(directory / "prepared.json").read_text(encoding="utf-8"))
    files, expected = input_bundle(meta["model_id"], meta["primary_count"], meta["seed"], meta["energy_keV"])
    require(meta == json.loads(json_text(expected)), "prepared metadata/lock/source changed; prepare a new directory")
    for name in files:
        require(sha256(local_path(directory / name)) == meta["files_sha256"][name], "immutable prepared input changed")
    return directory, meta


def python_versions():
    versions = {"python": platform.python_version(), "numpy": np.__version__}
    for name in ("PyYAML", "h5py", "remage"):
        try:
            versions[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            versions[name] = "not available in this Python"
    return versions


def run(directory):
    directory, meta = read_prepared(directory)
    require(set(p.name for p in directory.iterdir()) == {"prepared.json", *meta["files_sha256"]},
            "run requires a fresh prepared directory; preserve prior evidence and prepare another")
    command = ["remage", "--flat-output", "-t", "1", "--rand-seed", str(meta["seed"]),
               "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"]
    versions = python_versions()
    status = {"status": "failed", "command": command, "versions": versions,
              "prepared_sha256": sha256(directory / "prepared.json")}
    with local_path(directory / "run.log").open("x", encoding="utf-8") as log:
        try:
            for name, cmd in (("remage", ["remage", "--version"]),
                              ("geant4", ["geant4-config", "--version"])):
                result = subprocess.run(cmd, cwd=directory, text=True, stdout=subprocess.PIPE,
                                        stderr=subprocess.STDOUT, check=True)
                versions[name] = result.stdout.strip()
                log.write(result.stdout)
            log.flush()
            result = subprocess.run(command, cwd=directory, stdout=log, stderr=subprocess.STDOUT, check=False)
            status["returncode"] = result.returncode
            require(result.returncode == 0, "remage failed; see run.log")
            log.flush()
            content = (directory / "run.log").read_text(encoding="utf-8", errors="replace")
            require(not re.search(r"COMMAND NOT FOUND|illegal application state|command refused|"
                                  r"parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)",
                                  content, re.I), "macro/Geant4 diagnostic failure; see run.log")
            truth = local_path(directory / "truth.lh5")
            require(truth.is_file(), "expected flat truth.lh5 missing; inspect preserved outputs")
            # Validate census, fields and geometry before recording successful runtime evidence.
            extract_flat(truth, meta)
            status.update(status="complete", source_lh5_sha256=sha256(truth))
        except Exception as error:
            log.write("\nHandoff run failed: " + str(error) + "\n")
            raise
        finally:
            publish_json(directory / "run.json", status)
    return status


def flat_columns(group):
    import h5py
    require(isinstance(group, h5py.Group), "expected LH5 table")
    require("t0" not in group, "reshaped output rejected; t0 must never be added to time")
    columns = {}
    length = None
    for name, dataset in group.items():
        require(isinstance(dataset, h5py.Dataset) and dataset.ndim == 1,
                "flat scalar columns required; reshaped output is unsupported")
        values = dataset[:]
        if length is None:
            length = len(values)
        require(len(values) == length, "inconsistent LH5 column lengths")
        if values.dtype.kind in "fc":
            require(values.dtype.kind != "c" and np.isfinite(values).all(), "nonfinite/complex LH5 data")
        columns[name] = values
    return columns


def column(group, columns, name, unit=None, integer=False):
    require(name in columns, "missing required field: " + group.name + "/" + name)
    values = columns[name]
    units = group[name].attrs.get("units", "")
    if isinstance(units, bytes):
        units = units.decode("utf-8")
    require(units == (unit or ""), "wrong or missing units for " + name)
    if integer:
        require(values.dtype.kind in "iu", "integer dtype required for " + name)
    else:
        require(values.dtype.kind == "f" and values.dtype.itemsize == 8,
                "float64 required for " + name)
    require(np.isfinite(values).all(), "nonfinite field " + name)
    return values


def extract_flat(path, meta):
    """Validate all rows before producing any JSON; no reshaping guesses or filtering."""
    import h5py
    validate_transform(meta["coordinate_transform"])
    points = [tuple(p) for p in meta["contour_rz_mm"]]
    validate_contour(points)
    with h5py.File(path, "r") as raw:
        require("vtx" in raw and "number_of_simulated_events" in raw, "absent primary vertex census")
        count_data = raw["number_of_simulated_events"]
        require(isinstance(count_data, h5py.Dataset) and count_data.shape == ()
                and count_data.dtype.kind in "iu", "invalid simulated primary count")
        count = int(count_data[()])
        require(count == meta["primary_count"] and count > 0, "primary count mismatch")
        vtx = raw["vtx"]
        vertices = flat_columns(vtx)
        ids = column(vtx, vertices, "evtid", integer=True)
        times = column(vtx, vertices, "time", "ns")
        n_part = column(vtx, vertices, "n_part", integer=True)
        for name in ("xloc", "yloc", "zloc"):
            column(vtx, vertices, name, "m")
        require(len(ids) == count and sorted(map(int, ids)) == list(range(count)),
                "vertex IDs must uniquely census every generated event")
        require(np.all(n_part == 1), "only one primary/vertex per event is supported")
        require(np.all(times >= 0), "negative primary time")
        require("particles" in raw, "absent primary-particle table")
        primary_group = raw["particles"]
        primary = flat_columns(primary_group)
        primary_ids = column(primary_group, primary, "evtid", integer=True)
        primary_pdg = column(primary_group, primary, "particle", integer=True)
        vertex_ids = column(primary_group, primary, "vertexid", integer=True)
        primary_energy = column(primary_group, primary, "ekin", "MeV")
        require(len(primary_ids) == count and sorted(map(int, primary_ids)) == list(range(count)),
                "primary particle IDs must uniquely match the vertex census")
        require(np.all(primary_pdg == 22) and np.all(vertex_ids == 0), "expected one primary gamma at vertex zero")
        require(np.allclose(primary_energy * 1000, meta["energy_keV"], rtol=1e-12, atol=1e-9),
                "primary photon energy disagrees with prepared source")
        momentum = np.column_stack([column(primary_group, primary, key, "MeV") for key in ("px", "py", "pz")])
        require(np.allclose(np.linalg.norm(momentum, axis=1), primary_energy, rtol=1e-12, atol=1e-12),
                "primary gamma momentum/energy mismatch")
        events = {int(eid): {"event_id": int(eid), "primary_time_ns": float(t), "steps": []}
                  for eid, t in zip(ids, times)}
        require(TABLE in raw, "missing Germanium step table")
        group = raw[TABLE]
        columns = flat_columns(group)
        eid = column(group, columns, "evtid", integer=True)
        energy = column(group, columns, "edep", "keV")
        time = column(group, columns, "time", "ns")
        tracks = column(group, columns, "trackid", integer=True)
        parents = column(group, columns, "parent_trackid", integer=True)
        particles = column(group, columns, "particle", integer=True)
        require(np.all(energy >= 0), "negative deposited energy")
        require(np.all(tracks > 0) and np.all(parents >= 0), "invalid track/parent ID")
        coordinates = {}
        for suffix in ("", "_pre", "_post"):
            global_m = np.column_stack([column(group, columns, axis + suffix, "m")
                                        for axis in ("xloc", "yloc", "zloc")])
            coordinates[suffix] = (global_m, to_local(global_m, meta["coordinate_transform"]))
        # Also check known unmapped distance units. All extras remain in the hashed raw LH5.
        for name in columns:
            if name.startswith("dist_to_surf"):
                column(group, columns, name, "m")
        surface_rows = []
        for row in range(len(energy)):
            event_id = int(eid[row])
            require(event_id in events, "foreign step evtid")
            require(time[row] >= events[event_id]["primary_time_ns"], "step precedes primary vertex")
            labels = {suffix or "deposit": membership(points, coords[1][row])
                      for suffix, coords in coordinates.items()}
            require("outside" not in labels.values(), f"row {row} lies outside canonical solid beyond tolerance")
            if "surface" in labels.values():
                surface_rows.append({"raw_row_index": row, "classifications": labels})
            step = {"raw_row_index": row, "energy_keV": float(energy[row]), "time_ns": float(time[row]),
                    "position_mm": coordinates[""][1][row].tolist(),
                    "global_position_m": coordinates[""][0][row].tolist(),
                    "pre_position_mm": coordinates["_pre"][1][row].tolist(),
                    "post_position_mm": coordinates["_post"][1][row].tolist(),
                    "track_id": int(tracks[row]), "parent_track_id": int(parents[row]),
                    "particle_pdg": int(particles[row])}
            events[event_id]["steps"].append(step)
        for event in events.values():
            deposited = math.fsum(step["energy_keV"] for step in event["steps"])
            require(deposited <= meta["energy_keV"] + 1e-6, "event energy exceeds its primary photon energy")
        result = {
            "schema_version": 1, "model_id": meta["model_id"], "model_sha256": meta["model_sha256"],
            "source_lh5_sha256": sha256(path), "geometry_sha256": meta["files_sha256"]["geometry.gdml"],
            "macro_sha256": meta["files_sha256"]["run.mac"],
            "units": {"energy": "keV", "length": "mm", "time": "ns"},
            "coordinate_transform": meta["coordinate_transform"], "primary_count": count,
            "events": [events[e] for e in sorted(events)],
            "source_fields": {"file": "truth.lh5", "step_table": TABLE,
                              "step_columns": sorted(columns), "vertex_columns": sorted(vertices),
                              "primary_columns": sorted(primary),
                              "policy": "Unmapped columns, attributes, auxiliary tables and global endpoints remain in raw LH5; no claim of complete Geant4 history"},
            "boundary": {"tolerance_mm": BOUNDARY_MM, "surface_rows": surface_rows,
                         "policy": "Surface includes points within tolerance; original coordinates never moved"},
            "energy_sum_keV": math.fsum(map(float, energy)),
            "primary_validation": {"particle_pdg": 22, "energy_keV": meta["energy_keV"],
                                   "count": count, "raw_kinematics_checked": True},
        }
    validate_interchange(result)
    return result


def validate_interchange(data):
    """Final internal integrity gate, also useful for downstream small-fixture checks."""
    require(data["schema_version"] == 1, "unsupported schema")
    require(data["units"] == {"energy": "keV", "length": "mm", "time": "ns"}, "wrong interchange units")
    validate_transform(data["coordinate_transform"])
    events = data["events"]
    require(type(data["primary_count"]) is int and len(events) == data["primary_count"], "event count mismatch")
    require([e["event_id"] for e in events] == list(range(data["primary_count"])), "event census/order mismatch")
    rows, energies = [], []
    for event in events:
        require(type(event["event_id"]) is int, "noninteger event ID")
        primary_time = numeric(event["primary_time_ns"])
        require(primary_time >= 0, "negative primary time")
        event_rows = []
        for step in event["steps"]:
            for key in ("raw_row_index", "track_id", "parent_track_id", "particle_pdg"):
                require(type(step[key]) is int, "noninteger " + key)
            require(step["raw_row_index"] >= 0 and step["track_id"] > 0 and step["parent_track_id"] >= 0,
                    "invalid row/track ID")
            rows.append(step["raw_row_index"])
            event_rows.append(step["raw_row_index"])
            energy = numeric(step["energy_keV"])
            require(energy >= 0 and numeric(step["time_ns"]) >= primary_time, "invalid step energy/time")
            energies.append(energy)
            for key in ("position_mm", "global_position_m", "pre_position_mm", "post_position_mm"):
                require(len(step[key]) == 3 and all(math.isfinite(numeric(v)) for v in step[key]), "invalid position")
            require(np.allclose(to_local(step["global_position_m"], data["coordinate_transform"]),
                                step["position_mm"], rtol=0, atol=1e-10), "inconsistent local/global position")
        require(event_rows == sorted(event_rows), "nondeterministic step order")
    require(sorted(rows) == list(range(len(rows))), "duplicate or missing raw row IDs")
    require(math.fsum(energies) == data["energy_sum_keV"], "deposited energy sum changed")
    json_text(data)  # No NaN/Inf anywhere in final JSON.


def extract(directory):
    directory, meta = read_prepared(directory)
    final = local_path(directory / "events.json")
    require(not final.exists() and not final.with_name(final.name + ".partial").exists(), "extraction output already exists")
    status = json.loads(local_path(directory / "run.json").read_text(encoding="utf-8"))
    require(status["status"] == "complete" and status["prepared_sha256"] == sha256(directory / "prepared.json"),
            "run did not complete against these inputs")
    truth = local_path(directory / "truth.lh5")
    require(sha256(truth) == status["source_lh5_sha256"], "raw LH5 changed since run")
    result = extract_flat(truth, meta)
    result["provenance"] = {"prepared_sha256": status["prepared_sha256"],
                            "run_sha256": sha256(directory / "run.json"),
                            "lock_sha256": meta["lock_sha256"], "versions": status["versions"],
                            "extractor_versions": python_versions(), "seed": meta["seed"],
                            "energy_keV": meta["energy_keV"], "scope": SCOPE, "omitted_hardware": OMITTED}
    publish_json(final, result)
    return final


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    prep = commands.add_parser("prepare")
    prep.add_argument("--model", choices=PINNED, required=True)
    prep.add_argument("--output", type=Path, required=True)
    prep.add_argument("--events", type=int, default=100)
    prep.add_argument("--seed", type=int, default=260925)
    prep.add_argument("--energy-kev", type=float, default=662)
    for name in ("run", "extract"):
        commands.add_parser(name).add_argument("--directory", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "prepare":
        print(prepare(args.model, args.output, args.events, args.seed, args.energy_kev))
    elif args.command == "run":
        print(json_text(run(args.directory)))
    else:
        print(extract(args.directory))


if __name__ == "__main__":
    main()
