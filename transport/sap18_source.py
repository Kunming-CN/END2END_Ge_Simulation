"""Closed additive SAP18 Cs137 adapter; exact frozen exporter and original helpers."""
import argparse,json,math,os,re,shutil,subprocess,sys,time
from pathlib import Path
import cs137 as cs
import handoff as h
import scenario_prepare as assembly
import scenario_source_portable as P
import ring_cs137 as R
sys.path.insert(0,str(h.ROOT/'tools'))
import sap18_workflow as models
MODEL=models.MODEL
MODELS=(MODEL,)
PREPARED_KIND='sap18_cs137_prepared_v1'
WINDOWS_ROOT=None
def source_hashes():return cs.source_hashes()
def sap18_source_hashes():
 return {'transport/sap18_source.py':h.sha256(Path(__file__)),
         'transport/scenario_prepare.py':h.sha256(Path(assembly.__file__)),
         'tools/sap18_workflow.py':h.sha256(Path(models.__file__))}
def validate_contour(points):return R.validate_contour(points)
def reference_volume(model):
 h.require(model==MODEL,'Unsupported SAP18 identity')
 return R.reference_volume('KMRC01_candidate')
def contour(model):
 _,doc,_,_=models.inputs(model);p=doc['detectors'][0]['semiconductor']['geometry']['polycone']
 points=[(h.numeric(r),h.numeric(z)) for r,z in zip(p['r'],p['z'])]
 validate_contour(points)
 h.require(math.isclose(h.revolved_volume(points),reference_volume(model),rel_tol=1e-12),'SAP18 independent volume mismatch')
 return points
def probes(model,points):
 h.require(model==MODEL,'Wrong SAP18 probe identity')
 # Exact checked mass contour equals KM; reuse its independent edge probes only.
 return R.probes('KMRC01_candidate',points)
def scenario():
 value=R.scenario();value['scenario']='LBNL-SAP18-nominal-v1';return value
def validate_report(report,model,mounting,expected_probes):
 h.require(model==MODEL,'Wrong SAP18 report identity')
 # Full materials/placements/volume/membership tests apply to the identical mass solid.
 return R.validate_report(report,'KMRC01_candidate',mounting,expected_probes)
def check_request(request):
 h.require(type(request) is dict and set(request)=={'detector','source_mode','source_pose','primary_count','seed'},'Unsupported SAP18 request keys')
 h.require(request['detector']==MODEL and request['source_mode']==P.CS137 and request['source_pose']=='nominal' and
           type(request['primary_count']) is int and request['primary_count'] in (20,500) and
           type(request['seed']) is int and 0<request['seed']<2147483647,'Unsupported SAP18 tuple')
 build=P.read_build_receipt(WINDOWS_ROOT);models.inputs(MODEL);scenario();contour(MODEL)
 marker={'kind':'sap18_source_execution_v1','adapter_ref':'transport/sap18_source.py',
         'adapter_sha256':h.sha256(Path(__file__)),'build_receipt_ref':P.BUILD_RECEIPT_REF,
         'build_receipt_sha256':h.sha256(h.ROOT/P.BUILD_RECEIPT_REF),'exporter_ref':P.EXPORTER_REF,
         'exporter_sha256':build['exporter']['sha256'],'exporter_bytes':build['exporter']['bytes']}
 pins={**sap18_source_hashes(),models.MODEL_REF:models.MODEL_SHA,models.DEPENDENCY:models.DEPENDENCY_SHA,
       P.BUILD_RECEIPT_REF:marker['build_receipt_sha256'],P.EXPORTER_REF:marker['exporter_sha256']}
 return {'kind':'sap18_source_checked_plan_v1','schema_version':1,'request':request,'execution_contract':marker,
         'portable_source_sha256':pins,'canonical_source_sha256':P.canonical_sources(),
         'upstream_sha256':cs.upstream_hashes(),'runtime':build['runtime'],'gamma_plan':None}

def prepare_cs137(model, output, exporter, events=20, seed=26100241):
    h.require(model in MODELS and type(events) is int and events in (20,500), "invalid ring/count")
    h.require(type(seed) is int and 0 < seed < 2147483647, "invalid seed")
    output,exporter=h.local_path(output),h.local_path(exporter)
    h.require(not output.exists(), "ring output exists; preserve prior evidence")
    h.require(exporter.is_file() and h.sha256(exporter) == check_request({"detector":MODEL,"source_mode":P.CS137,"source_pose":"nominal","primary_count":events,"seed":seed})["execution_contract"]["exporter_sha256"], "existing native exporter missing/changed")
    frozen=source_hashes(); ring_frozen=sap18_source_hashes(); upstream=cs.upstream_hashes()
    points=contour(model); mounting=scenario(); expected_probes=probes(model,points)
    checked=check_request({"detector":MODEL,"source_mode":P.CS137,"source_pose":"nominal","primary_count":events,"seed":seed})
    output.mkdir(parents=True)
    h.publish_json(output/"portable-plan.json",checked)
    P.runtime_data(output,checked["runtime"],P.CS137)
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
        h.require(source_hashes() == frozen and sap18_source_hashes() == ring_frozen, "ring adapter changed before geometry launch")
        start=time.perf_counter()
        with (output/"geometry.log").open("x") as log:
            result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=False)
        status.update(command=command,returncode=result.returncode,native_geometry_wall_s=time.perf_counter()-start)
        h.require(result.returncode == 0, "native ring geometry failed; preserve log/report")
        h.require(not re.search(r"\*\*\*\s*(Error|Fatal)|Overlap is detected|cannot open|failed to read|cryostat_export:",(output/"geometry.log").read_text(errors="replace"),re.I), "native ring diagnostic failure")
        report=cs.load(output/"geometry-report.json")
        validate_report(report,model,mounting,expected_probes)
        h.require(source_hashes() == frozen and sap18_source_hashes() == ring_frozen and cs.upstream_hashes() == upstream, "ring source changed during geometry check")
        h.require(all(h.sha256(output/n) == digest for n,digest in inputs.items()), "ring prepared geometry inputs changed")
        models.validate(model_contract)
        h.write_new(output/"run.mac",cs.macro_text(report,events,mounting["source"]["position_global_mm"]))
        meta={"kind":PREPARED_KIND,"producer_adapter":"sap18_cs137_v1","model_id":model,"model_sha256":model_contract["source_model_sha256"],"model_contract":model_contract,
              "primary_count":events,"seed":seed,"source_pdg":cs.ION,"source_position_global_mm":mounting["source"]["position_global_mm"],
              "clock_policy":"remage_initial_decay_secondaries_zero","daughter_lifetime_limit_ns":-1,
              "coordinate_transform":mounting["coordinate_transform"],"contour_rz_mm":points,"grouping_policy":dict(cs.POLICY),
              "decay_photon_line_window_keV":mounting["decay_photon_line_window_keV"],"source_sha256":frozen,"sap18_source_sha256":ring_frozen,"upstream_sha256":upstream,
              "exporter_sha256":h.sha256(exporter),"probes":expected_probes,"analytic_volume_mm3":reference_volume(model),
              "native_geometry_wall_s":status["native_geometry_wall_s"],"mounting_contract":mounting["mounting_contract"],
              "material_tables":{"stp/"+v["name"]:v["material"] for v in report["volumes"] if v["name"] != "ledger_0_PV"},
              "unscored_volumes":[{"name":"ledger_0_PV","material":"G4_AIR","reason":"unscored default world region; no full energy closure claim"}],
              "execution_contract":checked["execution_contract"],"portable_source_sha256":checked["portable_source_sha256"],
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
    checked=check_request({"detector":MODEL,"source_mode":P.CS137,"source_pose":"nominal","primary_count":meta["primary_count"],"seed":meta["seed"]})
    h.require(cs.load(directory/"portable-plan.json")==checked and meta["execution_contract"]==checked["execution_contract"] and meta["portable_source_sha256"]==checked["portable_source_sha256"],"SAP18 execution/build binding changed")
    P.recheck_runtime_data(cs.load(directory/"runtime/runtime.json"),P.CS137)
    h.require(meta["kind"] == PREPARED_KIND and meta["model_id"] in MODELS, "wrong ring preparation")
    h.require(meta["source_sha256"] == source_hashes(), "ring adapter changed; prepare a fresh run")
    h.require(meta["sap18_source_sha256"] == sap18_source_hashes(), "ring implementation changed; prepare a fresh run")
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
    manifest={"kind":cs.KIND,"producer_adapter":"sap18_cs137_v1","status":"complete","primary_count":count,"global_decay_id_range":[0,count-1],
              "model_id":meta["model_id"],"model_sha256":meta["model_sha256"],"model_contract":meta["model_contract"],
              "source_lh5":"../truth.lh5","source_lh5_sha256":run["source_lh5_sha256"],"prepared_sha256":h.sha256(directory/"prepared.json"),"run_sha256":h.sha256(directory/"run.json"),
              "source_sha256":meta["source_sha256"],"sap18_source_sha256":meta["sap18_source_sha256"],"config_sha256":meta["files_sha256"]["scenario.json"],"geometry_sha256":meta["files_sha256"]["geometry.gdml"],"macro_sha256":meta["files_sha256"]["run.mac"],
              "units":{"energy":"keV","length":"mm","time":"ns"},"coordinate_transform":meta["coordinate_transform"],"grouping_policy":meta["grouping_policy"],"clock_policy":meta["clock_policy"],
              "processes":processes,"chunks":chunks,"raw_tables":tables,"uid_aliases":aliases,"unscored_volumes":meta["unscored_volumes"],"decay_photon_line_window_keV":meta["decay_photon_line_window_keV"],
              "raw_track_energy_unit":"MeV","raw_position_unit":"m","mounting_contract":meta["mounting_contract"],
              "execution_contract":meta["execution_contract"],"portable_source_sha256":meta["portable_source_sha256"],
              "ledger":{"kind":"recorded-only","full_energy_closure":None,"missing_closure":["world-air deposition (unscored default region)","terminal escape energy","neutrino escape balance","complete decay/recoil accounting"],"passive_raw_rows":"hashed truth.lh5; event material sums in JSONL"}}
    h.publish_json(directory/"stream/manifest.json",manifest)
    return manifest


def check_stage(directory,stage):
 d,m=read_prepared(directory)
 request={'detector':MODEL,'source_mode':P.CS137,'source_pose':'nominal','primary_count':m['primary_count'],'seed':m['seed']}
 checked=check_request(request)
 if stage in ('radiation','event_ledger'):
  run=cs.load(d/'run.json');h.require(run['status']=='complete' and run['returncode']==0 and
   run['prepared_sha256']==h.sha256(d/'prepared.json') and run['source_lh5_sha256']==h.sha256(d/'truth.lh5'),'SAP18 radiation receipt mismatch')
  cs.validate_actual_probe(d/'truth.lh5',m)
 if stage=='event_ledger':
  manifest=cs.load(d/'stream/manifest.json')
  h.require(manifest['producer_adapter']=='sap18_cs137_v1' and manifest['model_contract']==models.model_contract() and
    manifest['prepared_sha256']==h.sha256(d/'prepared.json') and manifest['run_sha256']==h.sha256(d/'run.json') and
    manifest['execution_contract']==checked['execution_contract'] and manifest['portable_source_sha256']==checked['portable_source_sha256'],
    'SAP18 stream source identity mismatch')
  # Bind the serialization to the actual flat LH5 reader; rehashed altered records fail.
  actual=cs.iter_decays(d/'truth.lh5',m)
  expected=(e for chunk in cs.iter_decay_chunks(d/'stream/manifest.json') for e in chunk)
  count=0
  import itertools
  for a,b in itertools.zip_longest(actual,expected):
   h.require(a==b,'SAP18 stream differs from actual original LH5 rows');count+=1
  h.require(count==m['primary_count'],'SAP18 streamed initial census mismatch')
 return checked
def main():
 global WINDOWS_ROOT
 parser=argparse.ArgumentParser(description=__doc__);sub=parser.add_subparsers(dest='command',required=True)
 p=sub.add_parser('check');p.add_argument('--request-json');p.add_argument('--directory');p.add_argument('--stage',choices=('geometry','radiation','event_ledger'))
 p.add_argument('--windows-root',required=True)
 p=sub.add_parser('prepare');p.add_argument('--request',required=True);p.add_argument('--checked-plan',required=True);p.add_argument('--output',required=True);p.add_argument('--windows-root',required=True)
 for name in ('run','extract'):
  p=sub.add_parser(name);p.add_argument('--directory',required=True);p.add_argument('--windows-root',required=True)
  if name=='extract':p.add_argument('--chunk-size',type=int,default=100)
 args=parser.parse_args();WINDOWS_ROOT=args.windows_root
 if args.command=='check':
  h.require(bool(args.request_json)!=bool(args.directory),'Choose request or saved stage')
  result=check_request(json.loads(args.request_json)) if args.request_json else check_stage(args.directory,args.stage)
 elif args.command=='prepare':
  request=cs.load(h.local_path(args.request));checked=check_request(request)
  h.require(cs.load(h.local_path(args.checked_plan))==checked,'SAP18 checked plan changed before execution')
  result=prepare_cs137(MODEL,args.output,str(h.ROOT/P.EXPORTER_REF),request['primary_count'],request['seed'])
 elif args.command=='run':result=run_cs137(args.directory)
 else:result=extract(args.directory,args.chunk_size)
 print(h.json_text(result))
if __name__=='__main__':main()
