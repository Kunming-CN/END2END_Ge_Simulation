"""Finite twenty-primary gamma transport/stream; no SSD or readout execution."""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import handoff as h
import cs137 as c
import scenario_prepare as s

KIND = "scenario_gamma_event_stream_v1"
RUN_KIND = "scenario_gamma_transport_run_v1"
PREPARATION_SHA = "4dd27621d0b91f53552428c5238d219459feff72cdcdd26609bc140460f9906c"
EXECUTABLES = {"remage": "040981e89bd8404886c7825aec675b414dc51f59003b83acf24fd45170550aaf",
               "geant4-config": "76f517185469d0cee6c6d497a14ecfb7df0a304f1c30e080bb2955c227a32584"}
EMLOW_ARCHIVE = "a43bb43f52f9765c8469356e992a768a51d42c64faa63527d9c7514627f1d877"
PREP_FILES = {"canonical.gdml", "probe-points.txt", "resolved-instance.json", "parameters.txt",
              "geometry.gdml", "geometry-report.json", "geometry.log", "run.mac"}
POSITIONS = {axis + suffix for suffix in ("", "_pre", "_post") for axis in ("xloc", "yloc", "zloc")}
STEP_INTS = {"evtid", "parent_trackid", "particle", "trackid"}
UIDS = {f"det{i+1:03d}": "/stp/" + entry[0] for i, entry in enumerate(s.LEDGER) if i}
COMMAND = ["remage", "--flat-output", "-t", "1", "--rand-seed", "26092631", "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"]


def checked_text(path, pins):
    raw = h.local_path(path).read_bytes()
    h.require(hashlib.sha256(raw).hexdigest() == pins[path], "parsed/text artifact differs from pinned bytes")
    return raw.decode("utf-8")


def producer_hashes():
    return {"transport/" + name: h.sha256(s.HERE / name) for name in
            ("scenario_transport.py", "Gamma.cmd", "gamma.sh", "cs137.py", "handoff.py",
             "scenario_prepare.py", "pixi.toml", "pixi.lock")}


def recheck(pins):
    for name, digest in pins.items():
        h.require(h.sha256(s.project_file(name)) == digest, "input/artifact changed: " + str(name))


def read_prepared(directory):
    d = h.local_path(directory)
    meta, digest = s.json_snapshot(h.local_path(d / "prepared.json"))
    s.exact([meta.get("kind"), meta.get("schema_version"), meta.get("status")], [s.KIND, 1, "prepared"], "unsupported preparation")
    model = meta.get("model_id")
    h.require(model in ("AK02", "SAP22"), "unsupported detector")
    config = s.ROOT / f"scenarios/m11a-{model.lower()}-mono_gamma_662_axis_v1-plus5mm.json"
    plan = s.check(config)
    for key in ("instance", "assets", "coordinate_transform", "source_position_global_mm"):
        s.exact(meta[key], plan[key], "prepared gamma contract mismatch: " + key)
    s.exact(meta["stages"], {"geometry": "geometry_checked", "source_macro": "source_macro_prepared",
        "transport": "transport_not_executed", "charge": "charge_not_executed", "readout": "readout_not_executed"}, "prepared stage mismatch")
    exporter = h.local_path(s.ROOT / ".local/m2a/cs137-build-v1/cryostat_export")
    h.require(h.sha256(s.HERE / "scenario_prepare.py") == PREPARATION_SHA, "preparation version changed")
    s.native_helpers()
    inventory = s.frozen_inventory(config, exporter)
    h.require(all(inventory.get(n) == v for n, v in plan["input_sha256"].items()), "checked plan changed before inventory")
    s.exact(meta["source_sha256"], inventory, "prepared source inventory mismatch; no old-version rebase")
    h.require(meta["exporter_sha256"] == s.EXPORTER_SHA256, "wrong exporter")
    h.require(set(meta["files_sha256"]) == PREP_FILES, "prepared file census mismatch")
    pins = {s.ROOT / name: value for name, value in inventory.items()}
    pins[d / "prepared.json"] = digest
    for name, value in meta["files_sha256"].items():
        h.require(type(value) is str and re.fullmatch(r"[0-9a-f]{64}", value), "invalid prepared digest")
        pins[h.local_path(d / name)] = value
    receipt, receipt_digest = s.json_snapshot(h.local_path(d / "prepare-receipt.json"))
    h.require(receipt["status"] == "complete" and receipt["kind"] == s.KIND
              and type(receipt["returncode"]) is int and receipt["returncode"] == 0, "incomplete geometry preparation")
    pins[d / "prepare-receipt.json"] = receipt_digest
    doc, points = h.load_model(model)
    s.exact(doc["detectors"][0]["semiconductor"]["temperature"], 78, "original temperature changed")
    s.exact([{"id": x["id"], "potential_V": x["potential"]} for x in doc["detectors"][0]["contacts"]],
            plan["assets"]["detector"]["contacts"], "original contacts changed")
    plan["contour_rz_mm"] = points
    s.exact(meta["contour_rz_mm"], points, "contour mismatch")
    report, report_digest = s.json_snapshot(h.local_path(d / "geometry-report.json"))
    h.require(report_digest == pins[d / "geometry-report.json"], "report snapshot differs from pin")
    s.validate_report(report, plan, h.probe_points(points))
    h.require(checked_text(d / "run.mac", pins) == s.source_macro(report, plan), "macro semantics changed, even if rehashed")
    h.require(checked_text(d / "canonical.gdml", pins) == h.gdml_text(points), "canonical geometry changed")
    h.require(checked_text(d / "probe-points.txt", pins) == "".join(" ".join(format(x, ".17g") for x in p["position_mm"]) + "\n"
              for p in h.probe_points(points)), "probe semantics changed")
    resolved, resolved_digest = s.json_snapshot(d / "resolved-instance.json")
    h.require(resolved_digest == pins[d / "resolved-instance.json"], "resolved snapshot differs from pin")
    s.exact(resolved, plan, "resolved instance changed")
    nominal = plan["nominal_geometry"]
    sp, cap = nominal["spacer"], nominal["capsule"]
    params = [*nominal["coordinate_transform"]["translation_global_mm"], *nominal["expected_vacuum_global_translation_mm"],
              *sp["vacuum_centre_mm"], sp["radius_mm"], sp["thickness_mm"], *plan["source_position_global_mm"],
              cap["radius_mm"], cap["thickness_mm"], cap["wall_mm"], 10000]
    h.require(checked_text(d / "parameters.txt", pins) == " ".join(format(v, ".17g") for v in params) + "\n", "parameter semantics changed")
    expected = {"source_pose_status": "native geometry checked for this preparation; nominal engineering pose",
        "legacy_source_sha256": c.source_hashes(), "upstream_sha256": c.upstream_hashes(),
        "overlap_seed": 26092632, "overlap_samples": 10000,
        "grouping_policy": {**c.POLICY, "horizon_ns": nominal["group_horizon_ns"]}, "energy_closure": None, "activity_Bq": None,
        "assumptions": [nominal["status"], "baseline nominal top reference: " + nominal["top_assumption"],
            "selected pose plus5mm; plus5mm is 5 mm beyond the nominal capsule/source centre along global +y",
            "source point and capsule/fill move together; capsule axis global +y", "overlap sampling is not geometry convergence",
            "planned count/seed/macro are inputs; no emitted event census or raw quantities exist"],
        "unknowns": nominal["unknowns"], "omitted": nominal["omitted"],
        "unscored_volumes": [{"name": "ledger_0_PV", "material": "G4_AIR",
            "reason": "world is unscored; world/escape/neutrino energy closure not established"}],
        "material_tables": {"stp/" + v["name"]: v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"}}
    for key, value in expected.items():
        s.exact(meta[key], value, "prepared provenance/limitations changed: " + key)
    h.require(set(meta) == set(expected) | {"kind", "schema_version", "status", "model_id", "instance", "assets",
        "source_position_global_mm", "coordinate_transform", "contour_rz_mm", "stages", "source_sha256", "exporter_sha256",
        "versions", "files_sha256", "native_geometry_wall_s"}, "unsupported prepared keys")
    s.exact(meta["versions"]["geant4_version_number"], 1132, "wrong prepared Geant4 version")
    h.require(h.numeric(meta["native_geometry_wall_s"]) >= 0, "invalid geometry timing")
    recheck(pins)
    return d, meta, pins


def columns(table, integers, floats, strings=()):
    h.require(set(table) == set(integers) | set(floats) | set(strings), "raw column census mismatch: " + table.name)
    for name in integers:
        c.field(table, name, integer=True)
    for name, unit in floats.items():
        c.field(table, name, unit)
    for name in strings:
        h.require(table[name].attrs.get("units", "") in ("", b""), "wrong string units")
        h.require(table[name].dtype.kind in "OSU", "wrong string type")


def gamma(rows, position):
    v, p = rows["vtx"], rows["particles"]
    h.require(len(v) == len(p) == 1 and v[0]["n_part"] == 1 and p[0]["vertexid"] == 0, "missing/duplicate primary")
    h.require(v[0]["time"] == 0 and p[0]["particle"] == 22, "wrong gamma identity/clock")
    expected = [0, -0.662, 0]
    for particle in (p[0], *[t for t in rows["tracks"] if t["parent_trackid"] == 0]):
        h.require(particle["particle"] == 22 and math.isclose(particle["ekin"], 0.662, rel_tol=0, abs_tol=1e-12)
                  and h.np.allclose([particle[a] for a in ("px", "py", "pz")], expected, rtol=0, atol=1e-12), "wrong gamma energy/momentum")
    h.require(h.np.allclose([1000 * v[0][a] for a in ("xloc", "yloc", "zloc")], position, rtol=0, atol=1e-10), "wrong source position/units")


def detector_origins(raw, meta):
    """One global Ge-scheme origin, not an event or nineteen material origins."""
    table = raw["detector_origins"]
    columns(table, (), {a: "m" for a in ("xloc", "yloc", "zloc")}, {"name"})
    s.exact(c.scalar(table.attrs.get("datatype", "")), "table{name,xloc,yloc,zloc}", "unsupported origin table metadata")
    rows = list(c.table_rows(table))
    h.require(len(rows) == 1 and rows[0]["name"] == "germanium", "detector-origin census/name mismatch")
    h.require(h.np.allclose([1000 * rows[0][a] for a in ("xloc", "yloc", "zloc")],
              meta["coordinate_transform"]["translation_global_mm"], rtol=0, atol=1e-10), "detector-origin translation/unit mismatch")
    return rows


def table_descriptor(table):
    return {"rows": len(next(iter(table.values()))), "attributes": {k: c.scalar(v) for k, v in table.attrs.items()},
        "columns": {name: {"dtype": str(ds.dtype), "units": c.scalar(ds.attrs.get("units", "")),
            "attributes": {k: c.scalar(v) for k, v in ds.attrs.items()}} for name, ds in table.items()}}


def tracks(rows, process_names, position):
    by_id = {}
    for t in rows:
        h.require(type(t["trackid"]) is int and t["trackid"] > 0 and t["trackid"] not in by_id
                  and type(t["parent_trackid"]) is int and t["parent_trackid"] >= 0, "invalid/duplicate track ID")
        h.require(t["time"] >= 0 and t["ekin"] >= 0, "negative track time/energy")
        h.require(t["parent_trackid"] == 0 or t["procid"] in process_names, "unknown secondary process")
        by_id[t["trackid"]] = t
    roots = [t for t in rows if t["parent_trackid"] == 0]
    h.require(len(roots) == 1 and roots[0]["time"] == 0, "missing/duplicate gamma root")
    h.require(h.np.allclose([1000 * roots[0][a] for a in ("xloc", "yloc", "zloc")], position, rtol=0, atol=1e-10), "root source mismatch")
    for t in rows:
        visited, parent = {t["trackid"]}, t["parent_trackid"]
        while parent:
            h.require(parent in by_id and parent not in visited, "missing/cyclic parent track")
            h.require(t["time"] + 1e-12 >= by_id[parent]["time"], "child birth precedes parent")
            visited.add(parent); parent = by_id[parent]["parent_trackid"]
    return by_id


def iter_events(path, meta):
    import h5py
    materials = meta["material_tables"]
    with h5py.File(path, "r") as raw:
        h.require(set(raw) == {"detector_origins", "vtx", "particles", "tracks", "processes", "stp", "number_of_simulated_events"}, "raw table census mismatch")
        detector_origins(raw, meta)
        count = raw["number_of_simulated_events"]
        h.require(count.shape == () and count.dtype.kind in "iu" and int(count[()]) == 20, "primary census mismatch")
        columns(raw["vtx"], {"evtid", "n_part"}, {"time": "ns", **{a: "m" for a in ("xloc", "yloc", "zloc")}})
        columns(raw["particles"], {"evtid", "particle", "vertexid"}, {a: "MeV" for a in ("ekin", "px", "py", "pz")})
        columns(raw["tracks"], {"evtid", "parent_trackid", "particle", "procid", "trackid"},
                {**{a: "MeV" for a in ("ekin", "px", "py", "pz")}, "time": "ns", **{a: "m" for a in ("xloc", "yloc", "zloc")}})
        columns(raw["processes"], {"procid"}, {}, {"name"})
        processes = list(c.table_rows(raw["processes"]))
        names = {p["procid"]: p["name"] for p in processes}
        h.require(len(names) == len(processes) and all(type(n) is str and n for n in names.values()), "invalid process census")
        h.require({"stp/" + name for name in raw["stp"] if name != "__by_uid__"} == set(materials), "material table census mismatch; absent is not zero")
        h.require("__by_uid__" in raw["stp"] and c.step_aliases(raw, materials) == UIDS, "UID alias census/mapping mismatch")
        for table in materials:
            floats = {"edep": "keV", "time": "ns", **{a: "m" for a in POSITIONS}}
            if table == "stp/germanium":
                floats.update({"dist_to_surf" + suffix: "m" for suffix in ("", "_pre", "_post")})
            columns(raw[table], STEP_INTS, floats)
        cursors = {key: c.Cursor(raw[key], 20) for key in ("vtx", "particles", "tracks", *materials)}
        counters = {key: 0 for key in cursors}
        for eid in range(20):
            rows = {key: cursor.take(eid) for key, cursor in cursors.items()}
            for table, records in rows.items():
                for row in records:
                    h.require(row["raw_row_index"] == counters[table], "lost/repeated raw row")
                    counters[table] += 1
            gamma(rows, meta["source_position_global_mm"])
            by_id = tracks(rows["tracks"], names, meta["source_position_global_mm"])
            sums, steps = {}, []
            for table, material in materials.items():
                values = []
                for row in rows[table]:
                    track = by_id.get(row["trackid"])
                    h.require(track is not None and (track["particle"], track["parent_trackid"]) == (row["particle"], row["parent_trackid"]), "deposit ancestry mismatch")
                    h.require(row["edep"] >= 0 and row["time"] >= 0 and row["time"] + 1e-12 >= track["time"], "negative/invalid deposit time/energy")
                    values.append(row["edep"])
                sums.setdefault(material, []).extend(values)
            for row in rows["stp/germanium"]:
                coords = {suffix: [row[a + suffix] for a in ("xloc", "yloc", "zloc")] for suffix in ("", "_pre", "_post")}
                local = {suffix: h.to_local(position, meta["coordinate_transform"]).tolist() for suffix, position in coords.items()}
                labels = {suffix or "deposit": h.membership(meta["contour_rz_mm"], xyz) for suffix, xyz in local.items()}
                h.require("outside" not in labels.values(), "Ge row outside canonical contour")
                steps.append({"raw_row_index": row["raw_row_index"], "energy_keV": row["edep"], "time_ns": row["time"],
                    "track_id": row["trackid"], "parent_track_id": row["parent_trackid"], "particle_pdg": row["particle"],
                    "global_position_m": coords[""], "position_mm": local[""], "pre_position_mm": local["_pre"],
                    "post_position_mm": local["_post"], "boundary_classifications": labels})
            edep = math.fsum(r["edep"] for r in rows["stp/germanium"])
            yield {"event_id": eid, "initial_primary_id": eid, "vtx": rows["vtx"], "particles": rows["particles"],
                "tracks": rows["tracks"], "material_rows": {k: rows[k] for k in materials}, "steps": steps,
                "truth_ge_edep_keV": edep, "zero_ge": edep == 0,
                "material_energy_keV": {k: math.fsum(v) for k, v in sums.items()}}
        h.require(all(cursor.next is None for cursor in cursors.values()), "unconsumed raw rows")
        h.require(all(counters[k] == len(next(iter(raw[k].values()))) for k in counters), "raw row census mismatch")


def validate_actual_probe(path, meta):
    summary = {"initial_gamma_primaries": 0, "zero_ge_primaries": 0, "ge_raw_rows": 0, "all_material_raw_rows": 0}
    for event in iter_events(path, meta):
        summary["initial_gamma_primaries"] += 1
        summary["zero_ge_primaries"] += int(event["zero_ge"])
        summary["ge_raw_rows"] += len(event["material_rows"]["stp/germanium"])
        summary["all_material_raw_rows"] += sum(map(len, event["material_rows"].values()))
    return summary


def emlow_manifest(directory, metadata):
    start = time.perf_counter()
    base = Path(directory).resolve()
    h.require(base.is_dir(), "missing EMLOW data directory")
    package, package_sha = s.json_snapshot(metadata)
    h.require(package["name"] == "geant4-data-emlow" and package["version"] == "8.6.1" and package["build"] == "hd8ed1ab_0"
              and package["sha256"] == EMLOW_ARCHIVE, "wrong locked EMLOW package")
    files, total = {}, 0
    for p in sorted(base.rglob("*")):
        h.require(not p.is_symlink(), "linked EMLOW data refused")
        if p.is_dir():
            continue
        h.require(p.is_file() and len(files) < 100000, "EMLOW file budget exceeded")
        size = p.stat().st_size; total += size
        h.require(total <= 2 * 1024**3, "EMLOW byte budget exceeded")
        files[p.relative_to(base).as_posix()] = {"bytes": size, "sha256": h.sha256(p)}
    h.require(files, "empty EMLOW dataset")
    return {"kind": "emlow_subtree_bytes_v1", "directory": str(base), "package_metadata": str(Path(metadata).resolve()),
        "package_metadata_sha256": package_sha, "archive_sha256": EMLOW_ARCHIVE, "files": files,
        "file_count": len(files), "bytes": total, "hash_wall_s": time.perf_counter() - start,
        "scope": "entire installed EMLOW subtree bytes, not a claim of exact files accessed by this run"}


def runtime(directory):
    prefix = Path(sys.prefix).resolve()
    values = {"versions": h.python_versions(), "executable_sha256": {"python": h.sha256(sys.executable)}}
    for name, version in (("remage", "1.1.0"), ("geant4-config", "11.3.2")):
        executable = shutil.which(name)
        h.require(executable is not None and Path(executable).resolve().is_relative_to(prefix), "missing/wrong locked runtime executable")
        h.require(h.sha256(executable) == EXECUTABLES[name], "runtime executable changed")
        p = subprocess.run([executable, "--version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True, shell=False)
        h.require(p.stdout.strip() == version, "runtime version mismatch")
        values["versions"][name] = version; values["executable_sha256"][name] = EXECUTABLES[name]
    h.require("G4LEDATA" in os.environ, "missing gamma EM data")
    data = Path(os.environ["G4LEDATA"]).resolve()
    h.require(data.is_relative_to(prefix), "EMLOW outside locked prefix")
    packages = list((prefix / "conda-meta").glob("geant4-data-emlow-8.6.1-*.json"))
    h.require(len(packages) == 1, "missing/ambiguous EMLOW package metadata")
    actual = emlow_manifest(data, packages[0])
    shared = h.local_path(directory.parent / "emlow-data.json")
    if shared.exists():
        saved = s.strict_load(shared)
        s.exact({k: v for k, v in actual.items() if k != "hash_wall_s"},
                {k: v for k, v in saved.items() if k != "hash_wall_s"}, "EMLOW bytes changed since paired manifest")
    else:
        h.publish_json(shared, actual)
    values["emlow_manifest"] = str(shared)
    values["emlow_manifest_sha256"] = h.sha256(shared)
    values["emlow_verification_wall_s"] = actual["hash_wall_s"]
    return values


def recheck_data(record):
    path = h.local_path(record["emlow_manifest"])
    h.require(h.sha256(path) == record["emlow_manifest_sha256"], "EMLOW manifest changed")
    saved = s.strict_load(path)
    actual = emlow_manifest(saved["directory"], saved["package_metadata"])
    s.exact({k: v for k, v in actual.items() if k != "hash_wall_s"},
            {k: v for k, v in saved.items() if k != "hash_wall_s"}, "EMLOW changed during stage")
    return actual["hash_wall_s"]


def run(directory):
    d, meta, pins = read_prepared(directory)
    h.require({p.name for p in d.iterdir()} == PREP_FILES | {"prepared.json", "prepare-receipt.json"}, "run requires fresh preparation; preserve existing attempt")
    producer = producer_hashes()
    recheck(pins)
    command = COMMAND.copy()
    receipt = {"kind": RUN_KIND, "status": "failed", "prepared_sha256": pins[d / "prepared.json"],
               "transport_source_sha256": producer, "command": command}
    start = time.perf_counter()
    try:
        receipt["runtime"] = runtime(d)
        recheck(pins); h.require(producer_hashes() == producer, "transport source changed before dispatch")
        with h.local_path(d / "run.log").open("x", encoding="utf-8") as log:
            t = time.perf_counter()
            result = subprocess.run(command, cwd=d, stdout=log, stderr=subprocess.STDOUT, check=False, shell=False)
            receipt["remage_wall_s"] = time.perf_counter() - t
        receipt["returncode"] = result.returncode
        h.require(type(result.returncode) is int and result.returncode == 0, "remage failed; retain raw/log")
        h.require(not re.search(r"COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected", (d / "run.log").read_text(errors="replace"), re.I), "native diagnostic failure")
        raw = h.local_path(d / "truth.lh5")
        receipt["source_lh5_sha256"] = h.sha256(raw)
        receipt["validation"] = validate_actual_probe(raw, meta)
        h.require(h.sha256(raw) == receipt["source_lh5_sha256"], "raw changed during validation")
        receipt["data_recheck_wall_s"] = recheck_data(receipt["runtime"])
        recheck(pins); h.require(producer_hashes() == producer, "transport source changed during run")
        receipt["status"] = "complete"
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        receipt["total_wall_s"] = time.perf_counter() - start
        h.publish_json(d / "run.json", receipt)
    return receipt


def extract(directory):
    import h5py
    d, meta, pins = read_prepared(directory)
    run_record, run_digest = s.json_snapshot(h.local_path(d / "run.json"))
    h.require(run_record["kind"] == RUN_KIND and run_record["status"] == "complete"
              and run_record["prepared_sha256"] == pins[d / "prepared.json"], "missing matching gamma run")
    h.require(run_record["transport_source_sha256"] == producer_hashes(), "transport producer changed")
    s.exact(run_record["command"], COMMAND, "run command/seed/thread changed")
    s.exact(run_record["returncode"], 0, "run exit code changed")
    raw = h.local_path(d / "truth.lh5")
    pins[d / "run.json"], pins[raw] = run_digest, run_record["source_lh5_sha256"]
    recheck(pins)
    dest = h.local_path(d / "stream")
    h.require(not dest.exists(), "extraction output exists; retain old derivative")
    dest.mkdir()
    receipt = {"kind": KIND, "status": "failed", "run_sha256": run_digest}
    start = time.perf_counter()
    try:
        partial = h.local_path(dest / "events-00000000.jsonl.partial")
        total = 0
        with partial.open("x", encoding="utf-8", newline="\n") as stream:
            for event in iter_events(raw, meta):
                h.require(event["event_id"] == event["initial_primary_id"] == total, "event ID mismatch")
                stream.write(json.dumps(event, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n")
                total += 1
            stream.flush(); os.fsync(stream.fileno())
        h.require(total == 20, "incomplete extraction")
        s.exact(run_record["validation"], validate_actual_probe(raw, meta), "run census differs from raw output")
        with h5py.File(raw, "r") as source:
            tables = {key: table_descriptor(source[key])
                for key in ("detector_origins", "vtx", "particles", "tracks", "processes", *meta["material_tables"])}
            origins = detector_origins(source, meta)
            processes = list(c.table_rows(source["processes"]))
            aliases = c.step_aliases(source, meta["material_tables"])
        recheck(pins); h.require(run_record["transport_source_sha256"] == producer_hashes(), "producer changed during extraction")
        recheck_data(run_record["runtime"])
        final = h.local_path(partial.with_suffix("")); os.link(partial, final); partial.unlink()
        manifest = {"kind": KIND, "schema_version": 1, "status": "complete", "primary_count": 20,
            "initial_primary_id_range": [0, 19], "source_count_unit": "initial synthetic gamma primaries",
            "model_id": meta["model_id"], "assets": meta["assets"], "source_position_global_mm": meta["source_position_global_mm"],
            "seed": 26092631, "threads": 1, "physics": {"EM": "Livermore", "default_production_cut_mm": 0.1, "sensitive_production_cut_mm": 0.01},
            "stored_temperature_K": meta["assets"]["detector"]["temperature_K"],
            "stored_contacts": meta["assets"]["detector"]["contacts"], "readout_contact_id": 1,
            "coordinate_transform": meta["coordinate_transform"], "prepared_sha256": pins[d / "prepared.json"],
            "run_sha256": run_digest, "source_lh5": "../truth.lh5", "source_lh5_sha256": pins[raw],
            "transport_source_sha256": producer_hashes(), "prepared_source_sha256": meta["source_sha256"],
            "chunks": [{"file": final.name, "count": 20, "first_initial_primary_id": 0, "sha256": h.sha256(final)}],
            "raw_tables": tables, "detector_origins": origins, "processes": processes, "uid_aliases": aliases, "material_tables": meta["material_tables"],
            "units": {"energy": "keV", "length": "mm", "time": "ns"}, "raw_track_energy_unit": "MeV", "raw_position_unit": "m",
            "clock_policy": "synthetic_primary_time_zero", "normalization": meta["assets"]["source"]["normalization"],
            "ledger": {"kind": "recorded-only", "full_energy_closure": None, "activity_Bq": None,
                "limitations": ["unscored world/escape energy", "births and scored STEP chords are not full trajectories", "20 primaries, low statistics", "nominal geometry, not as-built"]},
            "unscored_volumes": meta["unscored_volumes"],
            "geometry_unknowns": meta["unknowns"], "omitted_hardware": meta["omitted"],
            "stages": {"transport": "transport_complete", "charge": "charge_not_executed", "readout": "readout_not_executed"}}
        h.publish_json(dest / "manifest.json", manifest)
        receipt["status"] = "complete"
        return manifest
    except Exception as error:
        receipt["error"] = str(error)
        raise
    finally:
        receipt["wall_s"] = time.perf_counter() - start
        h.publish_json(dest / "extract-receipt.json", receipt)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("check", "run", "extract"))
    parser.add_argument("--prepared", required=True)
    args = parser.parse_args()
    if args.command == "check":
        d, meta, _ = read_prepared(args.prepared)
        result = {"kind": RUN_KIND, "status": "checked_only", "model_id": meta["model_id"], "planned_primaries": 20}
    else:
        result = run(args.prepared) if args.command == "run" else extract(args.prepared)
    print(h.json_text(result), end="")


if __name__ == "__main__":
    main()
