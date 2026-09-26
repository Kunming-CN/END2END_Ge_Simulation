"""Nominal cryostat Cs137 transport and event-complete streaming, never SSD physics.

Run in the existing locked environment. Preparation includes a native text import;
failed inputs/runs/extractions are retained and cannot be overwritten.
"""
import argparse
import itertools
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time

import handoff as h

HERE = Path(__file__).resolve().parent
KIND = "cs137_decay_stream_v1"
ION = 1000551370
LINE = [660, 663]
POLICY = {"name": "nominal_isolated_windows_v1", "horizon_ns": 100000,
          "interval": "[origin, origin+horizon)", "state_at_group_start": "reset",
          "tail": "truncate at horizon; recovery not established",
          "activity_live_time_pileup_claim": False}


def load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def source_hashes():
    files = ["cs137.py", "cryostat_export.cc", "cryostat_nominal.json", "handoff.py",
             "cryostat-source.json", "pixi.toml", "pixi.lock", "CMakeLists.txt"]
    return {p: h.sha256(HERE / p) for p in files}


def upstream_hashes():
    result = {}
    for item in load(HERE / "cryostat-source.json")["files"]:
        p = h.local_path(h.ROOT / ".local/transport/LBNL" / item["name"])
        h.require(h.sha256(p) == item["sha256"], "changed upstream original: " + item["name"])
        result[item["name"]] = item["sha256"]
    return result


def group_deposits(steps, horizon_ns=100000):
    h.require(math.isfinite(horizon_ns) and horizon_ns > 0, "invalid horizon")
    seen = set()
    for s in steps:
        i = s["raw_row_index"]
        h.require(type(i) is int and i >= 0 and i not in seen, "duplicate/invalid raw row")
        seen.add(i)
        h.require(math.isfinite(s["time_ns"]) and s["time_ns"] >= 0 and
                  math.isfinite(s["energy_keV"]) and s["energy_keV"] >= 0, "bad step time/energy")
    rows = sorted((s for s in steps if s["energy_keV"] > 0),
                  key=lambda s: (s["time_ns"], s["raw_row_index"]))
    groups = []
    for s in rows:
        if not groups or s["time_ns"] - groups[-1]["origin_time_ns"] >= horizon_ns:
            previous = groups[-1] if groups else None
            groups.append({"group_id": len(groups), "origin_time_ns": s["time_ns"],
                           "horizon_ns": horizon_ns, "row_indices": [], "relative_times_ns": [],
                           "tail_truncated_possible": True,
                           "recovery_not_established": previous is not None,
                           "boundary_split_within_horizon": bool(previous and
                               s["time_ns"] - previous["last_deposit_time_ns"] < horizon_ns),
                           "electronics_state": "reset_nominal_isolated_window"})
        g = groups[-1]
        g["row_indices"].append(s["raw_row_index"])
        g["relative_times_ns"].append(s["time_ns"] - g["origin_time_ns"])
        g["last_deposit_time_ns"] = s["time_ns"]
    return groups


def validate_group_map(steps, groups, horizon_ns):
    h.require(groups == group_deposits(steps, horizon_ns), "missing/duplicate/changed group assignment")


def macro_text(report, count, source):
    lines = ["# Nominal curved-cap top; conditional decay clock, not activity clock."]
    for i, v in enumerate(report["volumes"]):
        # Geant4 reserves the world region; do not assign SensitiveRegion to it.
        if v["name"] == "ledger_0_PV":
            continue
        scheme = "Germanium" if v["name"] == "germanium" else "Scintillator"
        h.require(type(v["copy_number"]) is int, "missing physical-volume copy number")
        lines.append(f'/RMG/Geometry/RegisterDetector {scheme} {v["name"]} {i+1} {v["copy_number"]}')
    lines += ["/RMG/Output/NtupleUseVolumeName true", "/RMG/Output/NtuplePerDetector true",
              "/RMG/Output/ActivateOutputScheme Track", "/RMG/Processes/LowEnergyEMPhysics Livermore",
              "/RMG/Processes/HadronicPhysics None", "/RMG/Processes/OpticalPhysics false",
              "/run/initialize", "/process/had/rdm/thresholdForVeryLongDecayTime 1e27 ns",
              "/RMG/Processes/Stepping/ResetInitialDecayTime true",
              "/RMG/Processes/Stepping/DaughterNucleusMaxLifetime -1 ns",
              "/RMG/Processes/Stepping/LargeGlobalTimeUncertaintyWarning 0.001 ns",
              "/RMG/Processes/DefaultProductionCut 0.1 mm",
              "/RMG/Processes/SensitiveProductionCut 0.01 mm"]
    for scheme in ("Germanium", "Scintillator"):
        lines += [f"/RMG/Output/{scheme}/StoreSinglePrecisionEnergy false",
                  f"/RMG/Output/{scheme}/StoreSinglePrecisionPosition false",
                  f"/RMG/Output/{scheme}/StoreTrackID true",
                  f"/RMG/Output/{scheme}/StepPositionMode Both",
                  f"/RMG/Output/{scheme}/Cluster/PreClusterOutputs false",
                  f"/RMG/Output/{scheme}/DiscardZeroEnergyHits false"]
    lines += ["/RMG/Output/Track/StoreSinglePrecisionPosition false",
              "/RMG/Output/Track/StoreSinglePrecisionEnergy false", "/RMG/Output/Track/StoreAlways true",
              "/RMG/Output/Vertex/SkipPrimaryVertexOutput false",
              "/RMG/Output/Vertex/StoreSinglePrecisionPosition false",
              "/RMG/Output/Vertex/StoreSinglePrecisionEnergy false",
              "/RMG/Output/Vertex/StorePrimaryParticleInformation true",
              "/RMG/Generator/Select GPS", "/gps/particle ion", "/gps/ion 55 137",
              "/gps/energy 0 eV", "/gps/pos/type Point",
              "/gps/pos/centre " + " ".join(format(v, ".17g") for v in source) + " mm",
              "/gps/time 0 ns", "/gps/number 1", f"/run/beamOn {count}"]
    return "\n".join(lines) + "\n"


def prepare_cs137(model, output, exporter, events=20, seed=26092631):
    h.require(type(events) is int and 1 <= events <= 100000, "invalid primary count")
    h.require(type(seed) is int and 0 < seed < 2147483647, "invalid seed")
    output, exporter = h.local_path(output), h.local_path(exporter)
    h.require(not output.exists(), "output exists; choose a fresh root")
    h.require(exporter.is_file(), "build the native cryostat_export target first")
    upstream = upstream_hashes()
    doc, points = h.load_model(model)
    scenario = load(HERE / "cryostat_nominal.json")
    h.validate_transform(scenario["coordinate_transform"])
    h.require(scenario["scenario"]=="LBNL-modular-nominal-v1" and
              scenario["upstream_entry"]=="stage.tg" and
              scenario["upstream_chain"]==["stage.tg","shield.tg","chamber.tg"],"unsupported assembly")
    h.require(scenario["spacer"]["material"]=="boron_nitride" and
              scenario["capsule"]["material"]=="G4_Al" and
              scenario["capsule"]["fill_material"]=="G4_POLYETHYLENE" and
              scenario["capsule"]["axis_global"]==[0,1,0],"unsupported nominal material/orientation")
    h.require((scenario["source"]["Z"],scenario["source"]["A"],scenario["source"]["kinetic_energy_eV"],
               scenario["source"]["distribution"])==(55,137,0,"point"),"unsupported source")
    h.require(h.np.allclose(h.np.array(scenario["coordinate_transform"]["translation_global_mm"])-
                           h.np.array(scenario["expected_vacuum_global_translation_mm"]),
                           scenario["crystal_in_vacuum_translation_mm"],rtol=0,atol=1e-12),"inconsistent local/global crystal positions")
    output.mkdir(parents=True)
    status = {"status": "failed", "stage": "prepare"}
    try:
        h.write_new(output / "canonical.gdml", h.gdml_text(points))
        probes = h.probe_points(points)
        h.write_new(output / "probe-points.txt", "".join(" ".join(format(x, ".17g") for x in p["position_mm"])+"\n" for p in probes))
        h.write_new(output / "scenario.json", h.json_text(scenario))
        sp, cap = scenario["spacer"], scenario["capsule"]
        parameters = [*scenario["coordinate_transform"]["translation_global_mm"],
                      *scenario["expected_vacuum_global_translation_mm"], *sp["vacuum_centre_mm"],
                      sp["radius_mm"], sp["thickness_mm"], *scenario["source"]["position_global_mm"],
                      cap["radius_mm"], cap["thickness_mm"], cap["wall_mm"], scenario["overlap_samples"]]
        h.write_new(output / "parameters.txt", " ".join(map(str, parameters)) + "\n")
        command = [str(exporter), str(h.ROOT / ".local/transport/LBNL/stage.tg"),
                   *(str(output / p) for p in ("canonical.gdml", "probe-points.txt", "parameters.txt", "geometry.gdml", "geometry-report.json"))]
        with (output / "geometry.log").open("x") as log:
            result = subprocess.run(command, stdout=log, stderr=subprocess.STDOUT, check=False)
        status["command"], status["returncode"] = command, result.returncode
        h.require(result.returncode == 0, "native import/check failed; preserve geometry.log/report")
        h.require(not re.search(r"\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read",
                                (output/"geometry.log").read_text(errors="replace"),re.I),
                  "native importer diagnostic failure; inspect geometry.log")
        report = load(output / "geometry-report.json")
        h.require(report["overlaps_passed"] and report["source_inside_fill"], "geometry check failed")
        h.require(math.isclose(report["crystal_volume_mm3"], h.reference_volume(model), rel_tol=1e-10), "solid volume mismatch")
        h.require(report["probes"] == [{"index": i, "classification": p["expected"]} for i,p in enumerate(probes)], "native Inside probe mismatch")
        ge = [v for v in report["volumes"] if v["name"] == "germanium"]
        h.require(len(ge)==1 and h.np.allclose(ge[0]["translation_global_mm"], scenario["coordinate_transform"]["translation_global_mm"], rtol=0, atol=1e-10)
                  and h.np.allclose(ge[0]["rotation_local_to_global"], scenario["coordinate_transform"]["rotation_local_to_global"], rtol=0, atol=1e-12), "crystal transform mismatch")
        h.write_new(output / "run.mac", macro_text(report, events, scenario["source"]["position_global_mm"]))
        meta = {"kind": "cs137_prepared_v1", "model_id": model, "model_sha256": h.PINNED[model],
                "primary_count": events, "seed": seed, "source_pdg": ION,
                "source_position_global_mm": scenario["source"]["position_global_mm"],
                "clock_policy": "remage_initial_decay_secondaries_zero", "daughter_lifetime_limit_ns": -1,
                "coordinate_transform": scenario["coordinate_transform"], "contour_rz_mm": points,
                "grouping_policy": {**POLICY, "horizon_ns": scenario["group_horizon_ns"]},
                "decay_photon_line_window_keV": scenario["decay_photon_line_window_keV"],
                "source_sha256": source_hashes(), "upstream_sha256": upstream,
                "exporter_sha256": h.sha256(exporter),
                "material_tables": {"stp/"+v["name"]: v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"},
                "unscored_volumes": [{"name": "ledger_0_PV", "material": "G4_AIR",
                    "reason": "Geant4 world retains default region; no world-air deposition ledger or full energy closure is claimed"}],
                "files_sha256": {p.name: h.sha256(p) for p in output.iterdir() if p.is_file()}}
        h.publish_json(output / "prepared.json", meta)
        status["status"] = "complete"
        return meta
    except Exception as e:
        status["error"] = str(e)
        raise
    finally:
        h.publish_json(output / "prepare-receipt.json", status)


def read_prepared(directory):
    d = h.local_path(directory)
    m = load(d / "prepared.json")
    h.require(m["kind"] == "cs137_prepared_v1", "wrong prepared kind")
    h.require(m["source_sha256"] == source_hashes(), "implementation/config changed; prepare a fresh run")
    h.require(m["upstream_sha256"] == upstream_hashes(), "upstream changed")
    h.load_model(m["model_id"])
    for name, digest in m["files_sha256"].items():
        h.require(Path(name).name == name and h.sha256(h.local_path(d/name)) == digest, "prepared input changed")
    return d, m


def installed_data():
    result = {}
    for variable, names in {"G4RADIOACTIVEDATA": ["z55.a137", "z56.a137"],
                            "G4LEVELGAMMADATA": ["z56.a137"],
                            "G4ENSDFSTATEDATA": ["ENSDFSTATE.dat"]}.items():
        h.require(variable in os.environ, "missing installed Geant4 dataset " + variable)
        directory = Path(os.environ[variable])
        result[variable] = {"directory_name": directory.name,
                            "files_sha256": {n: h.sha256(directory/n) for n in names}}
    return result


def run_cs137(directory):
    d, m = read_prepared(directory)
    h.require(set(p.name for p in d.iterdir()) == {*m["files_sha256"], "prepared.json", "prepare-receipt.json"}, "run requires fresh prepared directory")
    command = ["remage", "--flat-output", "-t", "1", "--rand-seed", str(m["seed"]),
               "-o", "truth.lh5", "-g", "geometry.gdml", "--", "run.mac"]
    receipt = {"status": "failed", "command": command, "prepared_sha256": h.sha256(d/"prepared.json"),
               "versions": h.python_versions()}
    start = time.perf_counter()
    try:
        with (d/"run.log").open("x", encoding="utf-8") as log:
            receipt["data"] = installed_data()
            for name, cmd in (("remage", ["remage", "--version"]), ("geant4", ["geant4-config", "--version"])):
                p = subprocess.run(cmd, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=True)
                receipt["versions"][name] = p.stdout.strip(); log.write(p.stdout)
                executable=shutil.which(cmd[0])
                h.require(executable is not None,"missing runtime executable")
                receipt.setdefault("software_executable_sha256",{})[cmd[0]]=h.sha256(executable)
            log.flush()
            t = time.perf_counter()
            p = subprocess.run(command, cwd=d, stdout=log, stderr=subprocess.STDOUT, check=False)
            receipt["remage_wall_s"] = time.perf_counter()-t
            receipt["returncode"] = p.returncode
        h.require(p.returncode == 0, "remage failed; see run.log")
        logtext = (d/"run.log").read_text(errors="replace")
        h.require(not re.search(r"COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected", logtext, re.I), "macro/geometry failure in run.log")
        receipt["source_lh5_sha256"] = h.sha256(d/"truth.lh5")
        receipt["validation"] = validate_actual_probe(d/"truth.lh5", m)
        receipt["status"] = "complete"
    except Exception as e:
        receipt["error"] = str(e)
        raise
    finally:
        receipt["total_wall_s"] = time.perf_counter()-start
        h.publish_json(d/"run.json", receipt)
    return receipt


def scalar(v):
    if hasattr(v, "item"): v = v.item()
    if isinstance(v, bytes): return v.decode("utf-8")
    h.require(isinstance(v, (str, int, float, bool)), "non-scalar raw field")
    if isinstance(v, float): h.require(math.isfinite(v), "nonfinite raw field")
    return v


def table_rows(table):
    """Bounded HDF5 reads; preserve physical row indices and every scalar column."""
    import h5py
    h.require(isinstance(table, h5py.Group) and "t0" not in table and
              "raw_row_index" not in table and len(table)>0, "flat unmodified table required")
    sizes = set()
    for ds in table.values():
        h.require(isinstance(ds,h5py.Dataset) and ds.ndim==1, "non-flat raw table")
        sizes.add(len(ds))
    h.require(len(sizes)==1, "column length mismatch")
    for first in range(0, sizes.pop(), 4096):
        block = {k: ds[first:first+4096] for k,ds in table.items()}
        for j in range(len(next(iter(block.values())))):
            yield {"raw_row_index": first+j, **{k:scalar(v[j]) for k,v in block.items()}}


def field(table, name, unit="", integer=False):
    h.require(name in table, "missing " + table.name + "/" + name)
    ds=table[name]; units=ds.attrs.get("units", "")
    if isinstance(units, bytes): units=units.decode()
    h.require(units==unit, "wrong units: " + ds.name)
    h.require(ds.dtype.kind in "iu" if integer else ds.dtype.kind=="f" and ds.dtype.itemsize==8,
              "wrong precision/type: " + ds.name)


def event_rows(table, count):
    field(table,"evtid",integer=True)
    last=-1
    for eid, rows in itertools.groupby(table_rows(table), lambda r:r["evtid"]):
        h.require(type(eid) is int and last < eid < count, "unordered, repeated or foreign event ID")
        last=eid
        yield eid,list(rows)


class Cursor:
    def __init__(self, table, count):
        self.it=iter(event_rows(table,count)); self.next=next(self.it,None)
    def take(self,eid):
        if self.next is None or self.next[0]>eid: return []
        h.require(self.next[0]==eid,"unconsumed event")
        rows=self.next[1]; self.next=next(self.it,None); return rows


def validate_decay_tracks(tracks, process_names):
    by_id={}
    for t in tracks:
        tid=t["trackid"]
        h.require(type(tid) is int and tid>0 and tid not in by_id,"duplicate/invalid track")
        h.require(t["time"]>=0 and t["ekin"]>=0,"negative track time/energy")
        # A primary has no creation process; retain its native sentinel verbatim.
        h.require(t["parent_trackid"]==0 or t["procid"] in process_names,"unknown secondary creation process")
        by_id[tid]=t
    roots=[t for t in tracks if t["parent_trackid"]==0]
    h.require(len(roots)==1 and roots[0]["particle"]==ION and roots[0]["ekin"]==0,"expected one zero-KE Cs137 root track")
    initial_children=[t for t in tracks if t["parent_trackid"]==roots[0]["trackid"]]
    h.require(initial_children and all(t["time"]==0 for t in initial_children),
              "initial decay children were not reset to time zero")
    for t in tracks:
        visited={t["trackid"]}; parent=t["parent_trackid"]
        while parent:
            h.require(parent in by_id and parent not in visited,"missing/cyclic parent track")
            visited.add(parent); parent=by_id[parent]["parent_trackid"]
    return by_id


def step_aliases(raw, materials):
    """Validate remage UID soft links without counting the same table twice."""
    import h5py
    group = raw["stp"].get("__by_uid__")
    if group is None:
        return {}
    h.require(isinstance(group, h5py.Group), "invalid UID alias group")
    aliases = {}
    for name in group:
        link = group.get(name, getlink=True)
        h.require(isinstance(link, h5py.SoftLink) and link.path.startswith("/stp/")
                  and link.path[1:] in materials, "foreign or non-soft UID alias")
        h.require(group[name].id == raw[link.path].id, "UID alias target mismatch")
        aliases[name] = link.path
    h.require(len(set(aliases.values())) == len(aliases), "duplicate UID alias target")
    h.require(set(aliases.values()) == {"/"+k for k in materials}, "UID alias census mismatch")
    return aliases


def iter_decays(path, meta):
    """Single serial LH5 only; monotone event blocks required, never load a campaign."""
    import h5py
    count=meta["primary_count"]
    with h5py.File(path,"r") as raw:
        census=raw["number_of_simulated_events"]
        h.require(census.shape==() and census.dtype.kind in "iu" and int(census[()])==count,"census mismatch")
        processes=list(table_rows(raw["processes"]))
        process_names={p["procid"]:p["name"] for p in processes}
        h.require(len(process_names)==len(processes),"duplicate process ID")
        required={"vtx","particles","tracks","stp/germanium"}
        h.require(all(k in raw for k in required),"missing required raw table")
        for key in ("vtx","particles","tracks"):
            field(raw[key],"evtid",integer=True)
        for key in ("particles","tracks"):
            for name in ("particle",): field(raw[key],name,integer=True)
            for name in ("ekin","px","py","pz"): field(raw[key],name,"MeV")
        field(raw["particles"],"vertexid",integer=True)
        field(raw["vtx"],"n_part",integer=True)
        for key in ("vtx","tracks"):
            field(raw[key],"time","ns")
            for name in ("xloc","yloc","zloc"): field(raw[key],name,"m")
        for name in ("trackid","parent_trackid","procid"): field(raw["tracks"],name,integer=True)
        materials=meta["material_tables"]
        step_aliases(raw, materials)
        actual={"stp/"+k for k in raw["stp"] if k != "__by_uid__"}
        h.require(actual==set(materials),"material table census mismatch (missing output is not zero)")
        for key in materials:
            for name in ("trackid","parent_trackid","particle"): field(raw[key],name,integer=True)
            field(raw[key],"edep","keV"); field(raw[key],"time","ns")
            for suffix in ("","_pre","_post"):
                for axis in ("xloc","yloc","zloc"): field(raw[key],axis+suffix,"m")
        cursors={key:Cursor(raw[key],count) for key in ["vtx","particles","tracks",*materials]}
        for eid in range(count):
            rows={key:c.take(eid) for key,c in cursors.items()}
            vtx,particles,tracks=rows["vtx"],rows["particles"],rows["tracks"]
            h.require(len(vtx)==len(particles)==1 and vtx[0]["n_part"]==1,"missing/duplicate vertex or primary")
            p=particles[0]
            h.require(p["particle"]==ION and p["vertexid"]==0 and p["ekin"]==0 and all(p[a]==0 for a in ("px","py","pz")),"primary must be zero-KE Cs137 ion")
            h.require(vtx[0]["time"]==0,"initial GPS vertex time must be zero")
            if "source_position_global_mm" in meta:
                h.require(h.np.allclose([vtx[0][a]*1000 for a in ("xloc","yloc","zloc")],meta["source_position_global_mm"],rtol=0,atol=1e-10),"source position mismatch")
            by_id=validate_decay_tracks(tracks,process_names)
            material_values={}
            for table,mat in materials.items():
                energies=[]
                for r in rows[table]:
                    h.require(r["edep"]>=0 and r["time"]>=0,"negative deposit/time")
                    t=by_id.get(r["trackid"])
                    h.require(t is not None and (t["particle"],t["parent_trackid"])==(r["particle"],r["parent_trackid"]),"deposit track link mismatch")
                    energies.append(r["edep"])
                material_values.setdefault(mat,[]).extend(energies)
            steps=[]
            for r in rows["stp/germanium"]:
                coords={suffix:[r[a+suffix] for a in ("xloc","yloc","zloc")] for suffix in ("","_pre","_post")}
                local={s:h.to_local(c,meta["coordinate_transform"]).tolist() for s,c in coords.items()}
                labels={s or "deposit":h.membership(meta["contour_rz_mm"],v) for s,v in local.items()}
                h.require("outside" not in labels.values(),"Ge row outside canonical contour")
                steps.append({"raw_row_index":r["raw_row_index"], "raw":r,
                              "energy_keV":r["edep"],"time_ns":r["time"],"track_id":r["trackid"],
                              "parent_track_id":r["parent_trackid"],"particle_pdg":r["particle"],
                              "global_position_m":coords[""],"position_mm":local[""],
                              "pre_position_mm":local["_pre"],"post_position_mm":local["_post"],
                              "boundary_classifications":labels})
            photons=[{"raw_row_index":t["raw_row_index"],"track_id":t["trackid"],
                      "parent_track_id":t["parent_trackid"],"time_ns":t["time"],"energy_keV":t["ekin"]*1000,
                      "creation_process":process_names[t["procid"]]} for t in tracks
                     if t["particle"]==22 and "radioactivedecay" in process_names[t["procid"]].lower()]
            window=meta.get("decay_photon_line_window_keV",LINE)
            yield {"global_decay_id":eid,"event_id":eid,"vtx":vtx,"particles":particles,"tracks":tracks,
                   "steps":steps,"material_energy_keV":{m:math.fsum(v) for m,v in material_values.items()},
                   "decay_photons":photons,"decay_photon_count":len(photons),
                   "line_photon_count":sum(window[0]<=p["energy_keV"]<=window[1] for p in photons),
                   "pulse_groups":group_deposits(steps,meta["grouping_policy"]["horizon_ns"])}
        h.require(all(c.next is None for c in cursors.values()),"unconsumed raw rows")


def validate_actual_probe(path, meta):
    summary={"decays":0,"zero_ge_decays":0,"decay_photons":0,"line_photons":0,
             "late_photons_beyond_horizon":0,"barium_pdg_codes":[],"ge_rows":0}
    pdgs=set()
    for e in iter_decays(path,meta):
        summary["decays"]+=1; summary["ge_rows"]+=len(e["steps"])
        summary["zero_ge_decays"]+=not any(s["energy_keV"]>0 for s in e["steps"])
        summary["decay_photons"]+=e["decay_photon_count"]; summary["line_photons"]+=e["line_photon_count"]
        summary["late_photons_beyond_horizon"]+=sum(p["time_ns"]>=meta["grouping_policy"]["horizon_ns"] for p in e["decay_photons"])
        pdgs.update(t["particle"] for t in e["tracks"] if abs(t["particle"])//10000==100056)
    summary["barium_pdg_codes"]=sorted(pdgs)
    summary["metastable_identity"]="raw PDGs/ancestry/times retained; suffix alone is not excitation validation"
    summary["initial_decay_children_zero_time_verified"]=True
    return summary


def write_chunks(events, destination, chunk_size):
    h.require(type(chunk_size) is int and 1<=chunk_size<=100,"chunk size must be 1..100")
    destination=h.local_path(destination)
    h.require(not destination.exists(),"stream output exists")
    destination.mkdir()
    chunks=[]; expected=0; stream=None; part=None
    try:
        for e in events:
            h.require(e["event_id"]==e["global_decay_id"]==expected,"duplicate/missing global decay ID")
            if expected%chunk_size==0:
                if stream is not None:
                    stream.flush(); os.fsync(stream.fileno()); stream.close()
                    final=part.with_suffix(""); os.link(part,final); part.unlink()
                    chunks[-1]["sha256"]=h.sha256(final)
                name=f"decays-{expected:08d}.jsonl"
                part=destination/(name+".partial"); stream=part.open("x",encoding="utf-8",newline="\n")
                chunks.append({"file":name,"first_global_decay_id":expected,"count":0})
            stream.write(json.dumps(e,sort_keys=True,separators=(",",":"),allow_nan=False)+"\n")
            chunks[-1]["count"]+=1; expected+=1
        if stream is not None:
            stream.flush(); os.fsync(stream.fileno()); stream.close()
            final=part.with_suffix(""); os.link(part,final); part.unlink(); chunks[-1]["sha256"]=h.sha256(final)
    finally:
        if stream is not None and not stream.closed: stream.close()
    return chunks,expected


def extract(directory, chunk_size=100):
    import h5py
    d,m=read_prepared(directory); run=load(d/"run.json")
    h.require(run["status"]=="complete" and run["prepared_sha256"]==h.sha256(d/"prepared.json"),"missing successful matching run")
    h.require(h.sha256(d/"truth.lh5")==run["source_lh5_sha256"],"raw LH5 changed")
    chunks,count=write_chunks(iter_decays(d/"truth.lh5",m),d/"stream",chunk_size)
    h.require(count==m["primary_count"],"incomplete extraction")
    with h5py.File(d/"truth.lh5","r") as raw:
        processes=list(table_rows(raw["processes"]))
        aliases=step_aliases(raw,m["material_tables"])
        tables={}
        for key in ("vtx","particles","tracks","processes",*m["material_tables"]):
            table=raw[key]
            tables[key]={"rows":len(next(iter(table.values()))),
                         "columns":{name:{"dtype":str(ds.dtype),
                                           "units":scalar(ds.attrs.get("units",""))}
                                    for name,ds in table.items()}}
    manifest={"kind":KIND,"status":"complete","primary_count":count,"global_decay_id_range":[0,count-1],
              "model_id":m["model_id"],"model_sha256":m["model_sha256"],"source_lh5":"../truth.lh5",
              "source_lh5_sha256":run["source_lh5_sha256"],"prepared_sha256":h.sha256(d/"prepared.json"),
              "run_sha256":h.sha256(d/"run.json"),"source_sha256":m["source_sha256"],
              "config_sha256":m["files_sha256"]["scenario.json"],"geometry_sha256":m["files_sha256"]["geometry.gdml"],
              "macro_sha256":m["files_sha256"]["run.mac"],"units":{"energy":"keV","length":"mm","time":"ns"},
              "coordinate_transform":m["coordinate_transform"],"grouping_policy":m["grouping_policy"],
              "clock_policy":m["clock_policy"],"processes":processes,"chunks":chunks,
              "raw_tables":tables,"uid_aliases":aliases,"unscored_volumes":m.get("unscored_volumes",[]),
              "decay_photon_line_window_keV":m["decay_photon_line_window_keV"],
              "raw_track_energy_unit":"MeV","raw_position_unit":"m",
              "ledger":{"kind":"recorded-only","full_energy_closure":None,
                        "missing_closure":["world-air deposition (unscored default region)","terminal escape energy","neutrino escape balance","complete decay/recoil accounting"],
                        "passive_raw_rows":"hashed truth.lh5; event material sums in JSONL"}}
    h.publish_json(d/"stream/manifest.json",manifest)
    return manifest


def iter_decay_chunks(manifest_path):
    path=h.local_path(manifest_path); m=load(path)
    h.require(m["kind"]==KIND and m["status"]=="complete","unfinished/wrong manifest")
    h.require(h.sha256(h.local_path(path.parent/m["source_lh5"]))==m["source_lh5_sha256"],"changed raw source")
    expected=0
    for c in m["chunks"]:
        h.require(Path(c["file"]).name==c["file"] and 1<=c["count"]<=100 and c["first_global_decay_id"]==expected,"invalid chunk mapping")
        p=h.local_path(path.parent/c["file"])
        h.require(h.sha256(p)==c["sha256"],"changed chunk")
        rows=[]
        with p.open(encoding="utf-8") as f:
            for line in f:
                h.require(len(rows)<c["count"],"extra chunk records")
                e=json.loads(line)
                h.require(e["global_decay_id"]==e["event_id"]==expected,"missing/duplicate decay")
                validate_group_map(e["steps"],e["pulse_groups"],m["grouping_policy"]["horizon_ns"])
                rows.append(e); expected+=1
        h.require(len(rows)==c["count"],"truncated chunk")
        yield rows
    h.require(expected==m["primary_count"] and m["global_decay_id_range"]==[0,expected-1],"incomplete decay census")


def main():
    p=argparse.ArgumentParser(description=__doc__); sub=p.add_subparsers(dest="command",required=True)
    q=sub.add_parser("prepare"); q.add_argument("--model",choices=h.PINNED,required=True)
    q.add_argument("--output",required=True); q.add_argument("--exporter",required=True)
    q.add_argument("--events",type=int,default=20); q.add_argument("--seed",type=int,default=26092631)
    for name in ("run","extract"):
        q=sub.add_parser(name); q.add_argument("--directory",required=True)
        if name=="extract": q.add_argument("--chunk-size",type=int,default=100)
    q=sub.add_parser("validate-probe"); q.add_argument("--raw",required=True)
    q.add_argument("--model",choices=h.PINNED,default="AK02"); q.add_argument("--events",type=int,default=20)
    q=sub.add_parser("check-stream"); q.add_argument("--manifest",required=True)
    a=p.parse_args()
    if a.command=="prepare": prepare_cs137(a.model,a.output,a.exporter,a.events,a.seed)
    elif a.command=="run": run_cs137(a.directory)
    elif a.command=="extract": extract(a.directory,a.chunk_size)
    elif a.command=="check-stream":
        print(json.dumps({"validated_decays":sum(len(c) for c in iter_decay_chunks(a.manifest))}))
    else:
        _,points=h.load_model(a.model)
        meta={"primary_count":a.events,"coordinate_transform":h.TRANSFORM,"contour_rz_mm":points,
              "material_tables":{"stp/germanium":"G4_Ge"},"grouping_policy":POLICY}
        print(h.json_text(validate_actual_probe(h.local_path(a.raw),meta)))


if __name__=="__main__": main()
