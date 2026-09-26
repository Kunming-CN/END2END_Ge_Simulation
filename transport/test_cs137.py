"""Synthetic contract tests; no transport launch. Actual probe is a separate CLI."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import h5py
import numpy as np
import cs137 as c
import handoff as h


def step(index, time, energy=1):
    return {"raw_row_index":index,"time_ns":time,"energy_keV":energy}


def fixture(path, count=3):
    """Serial complete Cs->Ba->gamma graph with a delayed missed photon."""
    def table(f,name,rows,units,integers):
        g=f.create_group(name)
        for k in rows[0]:
            values=[r[k] for r in rows]
            if k in integers: values=np.asarray(values,dtype="int64")
            elif k != "name": values=np.asarray(values,dtype="float64")
            ds=g.create_dataset(k,data=values,dtype=h5py.string_dtype() if k=="name" else None)
            if k in units: ds.attrs["units"]=units[k]
    xyz={"xloc":0.,"yloc":0.,"zloc":0.}
    v=[dict(evtid=e,n_part=1,time=0.,**xyz) for e in range(count)]
    p=[dict(evtid=e,vertexid=0,particle=c.ION,ekin=0.,px=0.,py=0.,pz=0.) for e in range(count)]
    t=[]
    for e in range(count):
        for tid,parent,pdg,proc,time,energy in [(1,0,c.ION,0,0.,0.),(2,1,1000561370,1,0.,0.),
                                               (3,2,22,1,120000000000.+e,0.661657)]:
            t.append(dict(evtid=e,trackid=tid,parent_trackid=parent,particle=pdg,procid=proc,
                          time=time,ekin=energy,px=0.,py=0.,pz=energy,**xyz))
    s=[]
    for energy,time in [(0.,120000000000.),(200.,120000000001.),(461.657,120000100001.)]:
        r=dict(evtid=0,trackid=3,parent_trackid=2,particle=22,edep=energy,time=time)
        for suffix in ("","_pre","_post"):
            r.update({"xloc"+suffix:0.01,"yloc"+suffix:0.,"zloc"+suffix:0.005})
        s.append(r)
    with h5py.File(path,"w") as f:
        f.create_dataset("number_of_simulated_events",data=count)
        table(f,"vtx",v,{"time":"ns",**{k:"m" for k in xyz}}, {"evtid","n_part"})
        table(f,"particles",p,{k:"MeV" for k in ("ekin","px","py","pz")},{"evtid","particle","vertexid"})
        table(f,"tracks",t,{"time":"ns",**{k:"m" for k in xyz},**{k:"MeV" for k in ("ekin","px","py","pz")}},
              {"evtid","trackid","parent_trackid","particle","procid"})
        table(f,"processes",[{"procid":0,"name":"primary"},{"procid":1,"name":"RadioactiveDecay"}],{}, {"procid"})
        table(f,"stp/germanium",s,{"edep":"keV","time":"ns",**{k:"m" for k in s[0] if "loc" in k}},
              {"evtid","trackid","parent_trackid","particle"})
    _,points=h.load_model("AK02")
    return {"primary_count":count,"coordinate_transform":h.TRANSFORM,"contour_rz_mm":points,
            "material_tables":{"stp/germanium":"G4_Ge"},"grouping_policy":c.POLICY}


class Cs137Tests(unittest.TestCase):
    def setUp(self):
        parent=h.ROOT/".local/peak-native-delivery"
        parent.mkdir(parents=True,exist_ok=True)
        self.tmp=tempfile.TemporaryDirectory(prefix="cs137-test-",dir=parent)
        self.root=Path(self.tmp.name)
    def tearDown(self): self.tmp.cleanup()
    def test_horizon_zero_delay_edges_and_tiny_positive(self):
        rows=[step(3,100000),step(0,0),step(1,99999.999999),step(2,50000,0),
              step(4,180000000000.,1e-30)]
        groups=c.group_deposits(rows)
        self.assertEqual([g["row_indices"] for g in groups],[[0,1],[3],[4]])
        self.assertTrue(groups[1]["boundary_split_within_horizon"])
        self.assertFalse(groups[2]["boundary_split_within_horizon"])
        self.assertEqual(groups[2]["relative_times_ns"],[0.])
        self.assertEqual(c.group_deposits([step(0,0,0)]),[])
        for bad in ([step(0,0),step(0,1)], [step(0,-1)], [step(0,0,-1)]):
            with self.assertRaises(ValueError): c.group_deposits(bad)
        changed=copy.deepcopy(groups); changed[0]["row_indices"].pop()
        with self.assertRaises(ValueError): c.validate_group_map(rows,changed,100000)
    def test_identities_zeros_raw_rows_and_delays(self):
        raw=self.root/"truth.lh5"; meta=fixture(raw)
        events=list(c.iter_decays(raw,meta))
        self.assertEqual([e["event_id"] for e in events],[0,1,2])
        self.assertEqual([len(e["steps"]) for e in events],[3,0,0])
        self.assertEqual([e["line_photon_count"] for e in events],[1,1,1])
        self.assertEqual(events[0]["steps"][0]["energy_keV"],0)
        self.assertEqual(events[0]["steps"][2]["time_ns"],120000100001.)
        self.assertEqual(events[0]["pulse_groups"][1]["row_indices"],[2])
        self.assertAlmostEqual(events[0]["material_energy_keV"]["G4_Ge"],661.657,delta=2*np.spacing(661.657))
        self.assertEqual(events[2]["tracks"][2]["parent_trackid"],2)
        self.assertEqual(c.validate_actual_probe(raw,meta)["late_photons_beyond_horizon"],3)
    def test_verified_uid_aliases_are_not_duplicate_tables(self):
        raw=self.root/"aliases.lh5"; meta=fixture(raw)
        with h5py.File(raw,"r+") as f:
            g=f["stp"].create_group("__by_uid__")
            g["det001"]=h5py.SoftLink("/stp/germanium")
        self.assertEqual(len(list(c.iter_decays(raw,meta))),3)
        with h5py.File(raw,"r+") as f:
            f["stp/__by_uid__/det002"]=h5py.SoftLink("/stp/germanium")
        with self.assertRaises(ValueError): list(c.iter_decays(raw,meta))
        with h5py.File(raw,"r+") as f:
            del f["stp/__by_uid__/det002"]
            del f["stp/__by_uid__/det001"]
            f["stp/__by_uid__/det001"]=h5py.SoftLink("/tracks")
        with self.assertRaises(ValueError): list(c.iter_decays(raw,meta))
    def test_missing_duplicate_foreign_and_wrong_primary(self):
        for name,table,column,row,value in [("duplicate","vtx","evtid",1,0),
                  ("missing","vtx","evtid",1,2),("foreign","stp/germanium","evtid",0,5),
                  ("wrong-ion","particles","particle",0,22),
                  ("parent","tracks","parent_trackid",2,99),
                  ("duplicate-track","tracks","trackid",2,2)]:
            raw=self.root/(name+".lh5"); meta=fixture(raw)
            with h5py.File(raw,"r+") as f: f[table][column][row]=value
            with self.subTest(name=name), self.assertRaises(ValueError): list(c.iter_decays(raw,meta))
    def test_wrong_precision_units_and_lengths(self):
        for mode in ("precision","units","length"):
            raw=self.root/(mode+".lh5"); meta=fixture(raw)
            with h5py.File(raw,"r+") as f:
                g=f["tracks"]; values=g["ekin"][:]; del g["ekin"]
                ds=g.create_dataset("ekin",data=values[:-1] if mode=="length" else values,
                                    dtype="float32" if mode=="precision" else "float64")
                ds.attrs["units"]="keV" if mode=="units" else "MeV"
            with self.subTest(mode=mode),self.assertRaises(ValueError): list(c.iter_decays(raw,meta))
    def test_chunk_stability_no_overwrite_and_interruption(self):
        raw=self.root/"truth.lh5"; meta=fixture(raw)
        outputs=[]
        for size in (1,2,100):
            dest=self.root/str(size)
            chunks,count=c.write_chunks(c.iter_decays(raw,meta),dest,size)
            self.assertEqual(count,3)
            outputs.append(b"".join((dest/x["file"]).read_bytes() for x in chunks))
            with self.assertRaises(ValueError): c.write_chunks([],dest,size)
        self.assertEqual(outputs[0],outputs[1]); self.assertEqual(outputs[1],outputs[2])
        def broken():
            yield {"event_id":0,"global_decay_id":0}
            raise ValueError("interrupted")
        with self.assertRaises(ValueError): c.write_chunks(broken(),self.root/"broken",100)
        self.assertFalse((self.root/"broken/manifest.json").exists())
        self.assertTrue((self.root/"broken/decays-00000000.jsonl.partial").exists())
        with self.assertRaises(ValueError):
            c.write_chunks([{"event_id":1,"global_decay_id":1}],self.root/"missing",100)
    def test_reader_tamper_and_census(self):
        raw=self.root/"truth.lh5"; meta=fixture(raw); dest=self.root/"stream"
        chunks,count=c.write_chunks(c.iter_decays(raw,meta),dest,2)
        m={"kind":c.KIND,"status":"complete","primary_count":count,"global_decay_id_range":[0,2],
           "source_lh5":"../truth.lh5","source_lh5_sha256":h.sha256(raw),"chunks":chunks,"grouping_policy":c.POLICY}
        path=dest/"manifest.json"; path.write_text(h.json_text(m))
        self.assertEqual(sum(map(len,c.iter_decay_chunks(path))),3)
        chunk=dest/chunks[0]["file"]; chunk.write_text(chunk.read_text()+"\n")
        with self.assertRaises(ValueError): list(c.iter_decay_chunks(path))
    def test_paths(self):
        for p in (h.ROOT/"transport/x",h.ROOT/".local",h.ROOT/".local/../models/x"):
            with self.assertRaises(ValueError): h.local_path(p)
        link=self.root/"link"
        try: link.symlink_to(self.root,target_is_directory=True)
        except OSError: pass
        else:
            with self.assertRaises(ValueError): h.local_path(link/"new")
    def test_macro_never_mono_gamma(self):
        text=c.macro_text({"volumes":[{"name":"germanium","copy_number":1},{"name":"ledger_0","copy_number":-10},{"name":"ledger_0_PV","copy_number":0}]},20,[0,37.073,.290])
        self.assertIn("RegisterDetector Germanium germanium 1 1",text)
        self.assertIn("RegisterDetector Scintillator ledger_0 2 -10",text)
        self.assertIn("/gps/ion 55 137",text)
        self.assertIn("/gps/energy 0 eV",text)
        self.assertIn("ResetInitialDecayTime true",text)
        self.assertIn("DaughterNucleusMaxLifetime -1 ns",text)
        self.assertIn("/RMG/Output/Track/StoreAlways true",text)
        self.assertNotIn("ledger_0_PV",text)
        self.assertNotIn("nucleusLimits",text)
        self.assertNotIn("662",text)


if __name__=="__main__": unittest.main()
