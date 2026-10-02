"""Additive ring Cs137 adapter; legacy AK02/SAP22 producers remain unchanged.

Uses the existing native cryostat exporter and flat, event-complete Cs137 ledger.
Ring mounting is the explicitly retained nominal engineering pose, not a survey.
"""
import argparse
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

import cs137 as cs
import handoff as h
import scenario_prepare as assembly

assembly.native_helpers()

sys.path.insert(0, str(h.ROOT / "tools"))
import ring_model_contract as models

MODELS = tuple(models.PINS)
PREPARED_KIND = "ring_cs137_prepared_v1"
NOMINAL_SHA256 = "9cad951c14213ac64d1e0c83c6ee44e7f4b9990d80979fd5bae35797daaf0edb"


def source_hashes():
    return cs.source_hashes()


def ring_source_hashes():
    return {"transport/ring_cs137.py": h.sha256(Path(__file__)),
            "transport/scenario_prepare.py": h.sha256(Path(assembly.__file__)),
            "tools/ring_model_contract.py": h.sha256(Path(models.__file__))}


def validate_contour(points):
    """Simple nonzero polygon including slants, without relaxing legacy checks."""
    h.require(points[0] == points[-1] and len(points) >= 4, "ring contour must be closed")
    h.require(all(r >= 0 and math.isfinite(r) and math.isfinite(z) for r, z in points), "invalid ring contour")
    h.require(len(set(points[:-1])) == len(points) - 1, "repeated ring vertex")
    edges = list(zip(points, points[1:]))
    def cross(a, b, p):
        return (b[0]-a[0])*(p[1]-a[1])-(b[1]-a[1])*(p[0]-a[0])
    def on(a, b, p):
        return cross(a,b,p) == 0 and all(min(a[k],b[k]) <= p[k] <= max(a[k],b[k]) for k in (0,1))
    for i, (a,b) in enumerate(edges):
        h.require(a != b, "zero ring edge")
        for j, (c,d) in enumerate(edges):
            if j <= i+1 or (i == 0 and j == len(edges)-1):
                continue
            ca, cb, cc, cd = cross(a,b,c), cross(a,b,d), cross(c,d,a), cross(c,d,b)
            intersection = (ca*cb < 0 and cc*cd < 0) or on(a,b,c) or on(a,b,d) or on(c,d,a) or on(c,d,b)
            h.require(not intersection, "self-intersecting/touching ring contour")
    h.require(h.revolved_volume(points) > 0, "degenerate ring contour")


def reference_volume(model):
    """Independent axial cylinders/frusta minus the cylindrical bore, mm^3."""
    if model == "GeRC02":
        segments = [(5.66,12.16,12.16),(3.59,12.16,11.98),(2,11.98,11.98),
                    (3.59,11.98,12.16),(5.66,12.16,12.16)]
        bore, height = 5.62, 20.5
    elif model == "KMRC01_candidate":
        segments = [(1,12.5,12.5),(1,11.8,11.8),(3.2,12.5,12.5),(1.6,12.5,11.3),
                    (4,11.3,11.3),(1.6,11.3,12.5),(4,12.5,12.5),(1,11.8,11.8),(1.6,12.5,12.5)]
        bore, height = 5.7, 19
    else:
        raise ValueError("unsupported ring")
    return math.pi * (math.fsum(d*(a*a+a*b+b*b)/3 for d,a,b in segments)-bore*bore*height)


def contour(model):
    _, doc, _, _ = models.inputs(model)
    h.require(doc["medium"] == "vacuum" and doc["grid"]["coordinates"] == "cylindrical" and len(doc["detectors"]) == 1, "unsupported ring coordinates")
    semi = doc["detectors"][0]["semiconductor"]
    geometry = semi["geometry"]
    h.require(semi["material"] == "HPGe" and set(geometry) == {"polycone"} and set(geometry["polycone"]) == {"r","z"}, "unsupported ring solid")
    poly = geometry["polycone"]
    h.require(len(poly["r"]) == len(poly["z"]), "invalid ring contour lengths")
    points = [(h.numeric(r),h.numeric(z)) for r,z in zip(poly["r"],poly["z"])]
    validate_contour(points)
    h.require(math.isclose(h.revolved_volume(points),reference_volume(model),rel_tol=1e-12), "independent ring volume mismatch")
    return points


def probes(model, points):
    top = 20.5 if model == "GeRC02" else 19
    waist_z, waist_r = (10.25,11.98) if model == "GeRC02" else (8.8,11.3)
    base = [("bulk",[10,0,5],"inside"),("bore",[0,0,5],"outside"),
            ("near_bore",[5,0,5],"outside"),("waist_bulk",[10,0,waist_z],"inside"),
            ("waist_surface",[waist_r,0,waist_z],"surface"),
            ("outside_waist",[waist_r+0.1,0,waist_z],"outside"),
            ("below",[10,0,-1],"outside"),("above",[10,0,top+1],"outside")]
    result = [{"name":n,"position_mm":xyz,"expected":e} for n,xyz,e in base]
    for i,((ra,za),(rb,zb)) in enumerate(zip(points,points[1:])):
        r,z = (ra+rb)/2,(za+zb)/2
        length=math.hypot(rb-ra,zb-za)
        nr,nz=-(zb-za)/length,(rb-ra)/length
        for offset in (-1e-5,0,1e-5):
            xyz=[r+offset*nr,0,z+offset*nz]
            result.append({"name":f"edge_{i}_offset_{offset:g}_mm","position_mm":xyz,
                           "expected":h.membership(points,xyz),"surface_offset_mm":offset})
        h.require(result[-2]["expected"] == "surface" and {result[-3]["expected"],result[-1]["expected"]} == {"inside","outside"}, "ring edge probes do not bracket surface")
    for probe in result:
        h.require(h.membership(points,probe["position_mm"]) == probe["expected"], "independent ring probe assertion failed")
    return result


def scenario():
    path = cs.HERE / "cryostat_nominal.json"
    h.require(h.sha256(path) == NOMINAL_SHA256, "nominal outer cryostat/source changed")
    value = cs.load(path)
    h.validate_transform(value["coordinate_transform"])
    h.require(value["coordinate_transform"]["rotation_local_to_global"] == assembly.ROTATION, "ring mounting rotation changed")
    value["scenario"] = "LBNL-ring-nominal-v1"
    value["mounting_contract"] = {
        "status": "checked nominal engineering placement; not experimentally surveyed",
        "parent_original_path": assembly.VACUUM,
        "local_axis_mapping": "local +z -> global +y; full bore retained",
        "crystal_base_global_mm": value["coordinate_transform"]["translation_global_mm"],
        "support": "unchanged 13 mm radius, 0.5 mm thick BN disk; no invented ring electrode/holder solids",
        "electrodes": "zero-thickness SSD boundaries; excluded from Geant4 mass geometry",
        "transport_mass": "entire canonical HPGe solid; no second Li dead-layer loss"}
    return value


def validate_report(report, model, mounting, expected_probes):
    h.require(set(report) == {"schema_version","geant4_version_number","overlap_seed","overlap_samples","source_inside_fill","crystal_volume_mm3","volumes","probes","overlaps_passed"}, "native report shape changed")
    for key,value in (("schema_version",1),("geant4_version_number",1132),("overlap_seed",26092632),("overlap_samples",10000)):
        h.require(type(report[key]) is int and report[key] == value, "native geometry setting changed: "+key)
    h.require(report["source_inside_fill"] is True and report["overlaps_passed"] is True, "ring containment/overlap failure")
    h.require(math.isclose(assembly.number(report["crystal_volume_mm3"]),reference_volume(model),rel_tol=1e-10), "native independent ring volume mismatch")
    h.require(report["probes"] == [{"index":i,"classification":p["expected"]} for i,p in enumerate(expected_probes)], "native ring membership mismatch")
    h.require(len(report["volumes"]) == len(assembly.LEDGER), "native ring ledger count changed")
    for found,expected in zip(report["volumes"],assembly.LEDGER):
        h.require((found["name"],found["original_path"],found["copy_number"],found["material"]) == expected and type(found["copy_number"]) is int, "native ring volume/material/copy/parent mismatch")
        h.require(found["overlap"] is False, "native ring overlap flag")
        density,fractions = assembly.MATERIALS[found["material"]]
        h.require(math.isclose(assembly.number(found["density_g_cm3"]),density,rel_tol=1e-12), "native ring density mismatch")
        elements = found["elements"]
        h.require(len(elements) == len(fractions) and {e["name"] for e in elements} == set(fractions), "native ring material elements mismatch")
        for element in elements:
            h.require(math.isclose(assembly.number(element["mass_fraction"]),fractions[element["name"]],rel_tol=1e-12), "native ring element fraction mismatch")
        h.validate_transform({"definition":h.TRANSFORM["definition"],"translation_global_mm":found["translation_global_mm"],"rotation_local_to_global":found["rotation_local_to_global"]})
    v=report["volumes"]
    assembly.placement(v[0],[0,0,0],h.TRANSFORM["rotation_local_to_global"])
    assembly.placement(v[5],mounting["expected_vacuum_global_translation_mm"],h.TRANSFORM["rotation_local_to_global"])
    assembly.placement(v[16],mounting["coordinate_transform"]["translation_global_mm"],assembly.ROTATION)
    spacer_global = [a+b for a,b in zip(mounting["expected_vacuum_global_translation_mm"],mounting["spacer"]["vacuum_centre_mm"])]
    assembly.placement(v[17],spacer_global,assembly.ROTATION)
    for volume in v[18:20]:
        assembly.placement(volume,mounting["source"]["position_global_mm"],assembly.ROTATION)
    assembly.require_source_inside_fill_mm(mounting["source"]["position_global_mm"],v[19])


def prepare_cs137(model, output, exporter, events=20, seed=26100241):
    h.require(model in MODELS and type(events) is int and 1 <= events <= 100000, "invalid ring/count")
    h.require(type(seed) is int and 0 < seed < 2147483647, "invalid seed")
    output,exporter=h.local_path(output),h.local_path(exporter)
    h.require(not output.exists(), "ring output exists; preserve prior evidence")
    h.require(exporter.is_file() and h.sha256(exporter) == assembly.EXPORTER_SHA256, "existing native exporter missing/changed")
    frozen=source_hashes(); ring_frozen=ring_source_hashes(); upstream=cs.upstream_hashes()
    points=contour(model); mounting=scenario(); expected_probes=probes(model,points)
    output.mkdir(parents=True)
    status={"status":"failed","stage":"prepare","model_id":model}
    try:
        model_contract=models.prepare(model,output/"effective-model")
        h.write_new(output/"canonical.gdml",h.gdml_text(points))
        h.write_new(output/"probe-points.txt","".join(" ".join(format(x,".17g") for x in p["position_mm"])+"\n" for p in expected_probes))
        h.write_new(output/"scenario.json",h.json_text(mounting))
        sp,cap=mounting["spacer"],mounting["capsule"]
        parameters=[*mounting["coordinate_transform"]["translation_global_mm"],*mounting["expected_vacuum_global_translation_mm"],*sp["vacuum_centre_mm"],sp["radius_mm"],sp["thickness_mm"],*mounting["source"]["position_global_mm"],cap["radius_mm"],cap["thickness_mm"],cap["wall_mm"],mounting["overlap_samples"]]
        h.write_new(output/"parameters.txt"," ".join(map(str,parameters))+"\n")
        inputs={p.name:h.sha256(p) for p in output.iterdir() if p.is_file()}
        command=[str(exporter),str(h.ROOT/".local/transport/LBNL/stage.tg"),*(str(output/p) for p in ("canonical.gdml","probe-points.txt","parameters.txt","geometry.gdml","geometry-report.json"))]
        h.require(source_hashes() == frozen and ring_source_hashes() == ring_frozen, "ring adapter changed before geometry launch")
        start=time.perf_counter()
        with (output/"geometry.log").open("x") as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        status.update(command=command,returncode=result.returncode,native_geometry_wall_s=time.perf_counter()-start)
        h.require(result.returncode == 0, "native ring geometry failed; preserve log/report")
        h.require(not re.search(r"\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read|cryostat_export:",(output/"geometry.log").read_text(errors="replace"),re.I), "native ring diagnostic failure")
        report=cs.load(output/"geometry-report.json")
        validate_report(report,model,mounting,expected_probes)
        h.require(source_hashes() == frozen and ring_source_hashes() == ring_frozen and cs.upstream_hashes() == upstream, "ring source changed during geometry check")
        h.require(all(h.sha256(output/n) == digest for n,digest in inputs.items()), "ring prepared geometry inputs changed")
        models.validate(model_contract)
        h.write_new(output/"run.mac",cs.macro_text(report,events,mounting["source"]["position_global_mm"]))
        meta={"kind":PREPARED_KIND,"producer_adapter":"ring_cs137_v1","model_id":model,"model_sha256":model_contract["source_model_sha256"],"model_contract":model_contract,
              "primary_count":events,"seed":seed,"source_pdg":cs.ION,"source_position_global_mm":mounting["source"]["position_global_mm"],
              "clock_policy":"remage_initial_decay_secondaries_zero","daughter_lifetime_limit_ns":-1,
              "coordinate_transform":mounting["coordinate_transform"],"contour_rz_mm":points,"grouping_policy":dict(cs.POLICY),
              "decay_photon_line_window_keV":mounting["decay_photon_line_window_keV"],"source_sha256":frozen,"ring_source_sha256":ring_frozen,"upstream_sha256":upstream,
              "exporter_sha256":h.sha256(exporter),"probes":expected_probes,"analytic_volume_mm3":reference_volume(model),
              "native_geometry_wall_s":status["native_geometry_wall_s"],"mounting_contract":mounting["mounting_contract"],
              "material_tables":{"stp/"+v["name"]:v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"},
              "unscored_volumes":[{"name":"ledger_0_PV","material":"G4_AIR","reason":"unscored default world region; no full energy closure claim"}],
              "files_sha256":{p.relative_to(output).as_posix():h.sha256(p) for p in output.rglob("*") if p.is_file()}}
        h.publish_json(output/"prepared.json",meta)
        status["status"]="complete"
        return meta
    except Exception as error:
        status["error"]=str(error)
        raise
    finally:
        h.publish_json(output/"prepare-receipt.json",status)


def read_prepared(directory):
    directory=h.local_path(directory); meta=cs.load(directory/"prepared.json")
    h.require(meta["kind"] == PREPARED_KIND and meta["model_id"] in MODELS, "wrong ring preparation")
    h.require(meta["source_sha256"] == source_hashes(), "ring adapter changed; prepare a fresh run")
    h.require(meta["ring_source_sha256"] == ring_source_hashes(), "ring implementation changed; prepare a fresh run")
    h.require(meta["upstream_sha256"] == cs.upstream_hashes(), "ring upstream changed")
    models.validate(meta["model_contract"])
    h.require(meta["model_sha256"] == meta["model_contract"]["source_model_sha256"] and meta["model_id"] == meta["model_contract"]["model_id"], "ring effective model binding mismatch")
    h.require(meta["contour_rz_mm"] == [list(p) for p in contour(meta["model_id"])], "ring contour changed")
    h.require(meta["grouping_policy"] == cs.POLICY, "ring grouping changed")
    mounting=scenario()
    h.require(cs.load(directory/"scenario.json") == mounting and meta["coordinate_transform"] == mounting["coordinate_transform"], "ring mount changed")
    h.require(meta["mounting_contract"] == mounting["mounting_contract"] and meta["source_position_global_mm"] == mounting["source"]["position_global_mm"], "ring source/mount binding mismatch")
    for ref,digest in meta["files_sha256"].items():
        h.require(type(ref) is str and "\\" not in ref and not Path(ref).is_absolute() and ".." not in Path(ref).parts, "invalid ring input reference")
        h.require(h.sha256(h.local_path(directory/ref)) == digest, "ring prepared input changed")
    expected_probes=probes(meta["model_id"],contour(meta["model_id"]))
    h.require(meta["probes"] == expected_probes, "ring probes changed")
    validate_report(cs.load(directory/"geometry-report.json"),meta["model_id"],mounting,expected_probes)
    h.require((directory/"run.mac").read_text(encoding="utf-8") == cs.macro_text(cs.load(directory/"geometry-report.json"),meta["primary_count"],meta["source_position_global_mm"]), "ring macro changed beyond exact count")
    return directory,meta


def run_cs137(directory):
    directory,meta=read_prepared(directory)
    expected={*meta["files_sha256"],"prepared.json","prepare-receipt.json"}
    h.require({p.relative_to(directory).as_posix() for p in directory.rglob("*") if p.is_file()} == expected, "ring run requires fresh preparation")
    command=["remage","--flat-output","-t","1","--rand-seed",str(meta["seed"]),"-o","truth.lh5","-g","geometry.gdml","--","run.mac"]
    receipt={"status":"failed","command":command,"prepared_sha256":h.sha256(directory/"prepared.json"),"versions":h.python_versions()}
    start=time.perf_counter()
    try:
        with (directory/"run.log").open("x",encoding="utf-8") as log:
            receipt["data"]=cs.installed_data()
            for name,cmd,expected_version in (("remage",["remage","--version"],"1.1.0"),("geant4",["geant4-config","--version"],"11.3.2")):
                result=subprocess.run(cmd,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT,check=True)
                receipt["versions"][name]=result.stdout.strip(); log.write(result.stdout)
                h.require(result.stdout.strip() == expected_version, "ring pinned runtime version mismatch")
                executable=shutil.which(cmd[0]); h.require(executable is not None,"missing runtime executable")
                receipt.setdefault("software_executable_sha256",{})[cmd[0]]=h.sha256(executable)
            log.flush(); production_start=time.perf_counter()
            result=subprocess.run(command,cwd=directory,stdout=log,stderr=subprocess.STDOUT,check=False)
            receipt["remage_wall_s"]=time.perf_counter()-production_start; receipt["returncode"]=result.returncode
        h.require(result.returncode == 0,"ring remage failed; preserve run.log")
        h.require(not re.search(r"COMMAND NOT FOUND|illegal application state|command refused|parameter out of range|macro.*(failed|error)|\*\*\*\s*(Error|Fatal)|Overlap is detected",(directory/"run.log").read_text(errors="replace"),re.I), "ring macro/geometry failure")
        read_prepared(directory)
        receipt["source_lh5_sha256"]=h.sha256(directory/"truth.lh5")
        receipt["validation"]=cs.validate_actual_probe(directory/"truth.lh5",meta)
        receipt["status"]="complete"
    except Exception as error:
        receipt["error"]=str(error)
        raise
    finally:
        receipt["total_wall_s"]=time.perf_counter()-start
        h.publish_json(directory/"run.json",receipt)
    return receipt


def extract(directory,chunk_size=100):
    import h5py
    directory,meta=read_prepared(directory); run=cs.load(directory/"run.json")
    h.require(run["status"] == "complete" and run["prepared_sha256"] == h.sha256(directory/"prepared.json"), "missing matching complete ring run")
    h.require(h.sha256(directory/"truth.lh5") == run["source_lh5_sha256"], "ring raw LH5 changed")
    chunks,count=cs.write_chunks(cs.iter_decays(directory/"truth.lh5",meta),directory/"stream",chunk_size)
    h.require(count == meta["primary_count"], "incomplete ring extraction")
    with h5py.File(directory/"truth.lh5","r") as raw:
        processes=list(cs.table_rows(raw["processes"])); aliases=cs.step_aliases(raw,meta["material_tables"])
        tables={key:{"rows":len(next(iter(raw[key].values()))),"columns":{name:{"dtype":str(ds.dtype),"units":cs.scalar(ds.attrs.get("units",""))} for name,ds in raw[key].items()}} for key in ("vtx","particles","tracks","processes",*meta["material_tables"])}
    manifest={"kind":cs.KIND,"producer_adapter":"ring_cs137_v1","status":"complete","primary_count":count,"global_decay_id_range":[0,count-1],
              "model_id":meta["model_id"],"model_sha256":meta["model_sha256"],"model_contract":meta["model_contract"],
              "source_lh5":"../truth.lh5","source_lh5_sha256":run["source_lh5_sha256"],"prepared_sha256":h.sha256(directory/"prepared.json"),"run_sha256":h.sha256(directory/"run.json"),
              "source_sha256":meta["source_sha256"],"ring_source_sha256":meta["ring_source_sha256"],"config_sha256":meta["files_sha256"]["scenario.json"],"geometry_sha256":meta["files_sha256"]["geometry.gdml"],"macro_sha256":meta["files_sha256"]["run.mac"],
              "units":{"energy":"keV","length":"mm","time":"ns"},"coordinate_transform":meta["coordinate_transform"],"grouping_policy":meta["grouping_policy"],"clock_policy":meta["clock_policy"],
              "processes":processes,"chunks":chunks,"raw_tables":tables,"uid_aliases":aliases,"unscored_volumes":meta["unscored_volumes"],"decay_photon_line_window_keV":meta["decay_photon_line_window_keV"],
              "raw_track_energy_unit":"MeV","raw_position_unit":"m","mounting_contract":meta["mounting_contract"],
              "ledger":{"kind":"recorded-only","full_energy_closure":None,"missing_closure":["world-air deposition (unscored default region)","terminal escape energy","neutrino escape balance","complete decay/recoil accounting"],"passive_raw_rows":"hashed truth.lh5; event material sums in JSONL"}}
    h.publish_json(directory/"stream/manifest.json",manifest)
    return manifest


def main():
    parser=argparse.ArgumentParser(description=__doc__); sub=parser.add_subparsers(dest="command",required=True)
    p=sub.add_parser("prepare"); p.add_argument("--model",choices=MODELS,required=True); p.add_argument("--output",required=True); p.add_argument("--exporter",required=True); p.add_argument("--events",type=int,default=20); p.add_argument("--seed",type=int,default=26100241)
    for name in ("run","extract"):
        p=sub.add_parser(name); p.add_argument("--directory",required=True)
        if name == "extract": p.add_argument("--chunk-size",type=int,default=100)
    p=sub.add_parser("check-stream"); p.add_argument("--manifest",required=True)
    args=parser.parse_args()
    if args.command == "prepare": result=prepare_cs137(args.model,args.output,args.exporter,args.events,args.seed)
    elif args.command == "run": result=run_cs137(args.directory)
    elif args.command == "extract": result=extract(args.directory,args.chunk_size)
    else: result={"validated_decays":sum(len(c) for c in cs.iter_decay_chunks(args.manifest))}
    print(h.json_text(result))


if __name__ == "__main__":
    main()
