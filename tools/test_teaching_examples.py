"""Focused saved-data and rendering contracts for the curated teaching reader."""
import copy
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile

import teaching_examples as teaching

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
NODE = os.environ.get("TEACHING_NODE") or shutil.which("node")


class TeachingExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.payload = teaching.build_payload(SITE)
        cls.html = teaching.render(cls.payload)

    def test_six_cases_equal_original_saved_ledgers_and_traces(self):
        self.assertEqual([(c["model"], c["event_id"], c["group_id"])
                          for c in self.payload["cases"]],
                         [(m, e, g) for m, e, g, _, _ in teaching.SELECTION])
        for model, folder in teaching.FOLDERS.items():
            selected = [c for c in self.payload["cases"] if c["model"] == model]
            with zipfile.ZipFile(SITE / folder / "ledgers.zip") as archive:
                traces = [json.loads(line) for line in archive.open("traces.jsonl")]
                scalars = [json.loads(line) for line in archive.open("scalars.jsonl")]
            for case in selected:
                key = (case["event_id"], case["group_id"])
                original = next(t for t in traces if (t["event_id"], t["group_id"]) == key)
                pulse = next(s for s in scalars if s.get("record_kind") == "pulse" and
                             (s["event_id"], s["group_id"]) == key)
                self.assertEqual(case["saved_trace"], original)
                self.assertEqual(case["pulse"], pulse)
                self.assertEqual(case["native_charge"]["induced_equivalent_energy_keV"][-1],
                                 pulse["final_induced_keV"])
                self.assertEqual(case["truth"]["event_id"], case["event_id"])
                self.assertEqual(case["decay"]["global_decay_id"], case["event_id"])

    def test_original_current_bins_integrate_to_recorded_electronics_charge(self):
        for case in self.payload["cases"]:
            model = self.payload["models"][case["model"]]
            charge, readout = case["native_charge"], case["pulse"]["readout"]
            dt = model["calibration"]["time_step_ns"]
            current = teaching.current_from_charge(
                charge["time_since_origin_ns"], charge["induced_equivalent_energy_keV"],
                model["calibration"]["ionisation_energy_eV"], dt,
                readout["readout_end_ns"], model["wiring"]["factor"])
            self.assertEqual(len(current), readout["original_sample_count"])
            integrated = math.fsum(current) * dt * 1e-18
            self.assertAlmostEqual(integrated, readout["current_balance"]["charge_change_C"],
                                   delta=max(readout["current_balance"]["tolerance_C"], 1e-29))
        km = next(c for c in self.payload["cases"] if c["model"] == "KMRC01_candidate")
        self.assertLess(km["pulse"]["final_induced_keV"], 0)
        self.assertEqual(self.payload["models"]["KMRC01_candidate"]["wiring"]["factor"], -1)
        self.assertTrue(km["pulse"]["readout"]["accepted"])

    def test_current_boundary_keeps_sign_tail_and_original_zero_bin(self):
        times, charge = [0, 2, 4, 6], [0, -10, -4, 2]
        before = copy.deepcopy((times, charge))
        current = teaching.current_from_charge(times, charge, 2.95, 2, 10, -1)
        self.assertEqual(current[0], 0)
        self.assertGreater(current[1], 0)
        self.assertLess(current[2], 0)
        self.assertEqual(current[-2:], [0, 0])
        clipped = teaching.current_from_charge(times, charge, 2.95, 2, 4, -1)
        self.assertEqual(len(clipped), 3)
        self.assertEqual(clipped, current[:3])
        self.assertEqual((times, charge), before)
        with self.assertRaisesRegex(ValueError, "original grid"):
            teaching.current_from_charge([0, 2, 10], [0, 1, 2], 2.95, 2, 10)
        with self.assertRaisesRegex(ValueError, "boundary"):
            teaching.current_from_charge(times, charge, 2.95, 2, 3)

    def test_selection_labels_do_not_change_physics_or_hide_caps(self):
        low = next(c for c in self.payload["cases"] if c["model"] == "SAP22" and c["event_id"] == 155)
        self.assertAlmostEqual(low["truth"]["decay_photons"][0]["energy_keV"], 32.2053811750089)
        self.assertIn("not partial absorption", low["explanation"])
        multi = next(c for c in self.payload["cases"] if c["model"] == "GeRC02" and c["event_id"] == 69)
        self.assertEqual(multi["positive_deposit_count"], 25)
        cap = next(c for c in self.payload["cases"] if c["model"] == "AK02")
        self.assertEqual(cap["pulse"]["transport_flags"]["step_limits"], 26)
        self.assertTrue(cap["pulse"]["readout"]["tail_truncated_possible"])
        self.assertEqual(self.payload["models"]["GeRC02"]["model_contract"]["annealing_time_minutes"], 50)

    def test_changed_sources_cannot_be_rebaselined_by_a_rehashed_receipt(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".local", prefix="teaching-contract-") as directory:
            site = Path(directory)
            for rel in teaching.SOURCE_SHA256:
                path = site / rel
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"changed input and new self-reported digest")
            self.assertTrue(teaching.available(site))
            with self.assertRaisesRegex(ValueError, "Pinned teaching source changed"):
                teaching.build_payload(site)
            (site / next(iter(teaching.SOURCE_SHA256))).unlink()
            self.assertFalse(teaching.available(site))

    def test_validation_reconstructs_samples_and_rejects_partial_or_mutated_outputs(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".local", prefix="teaching-contract-") as directory:
            site = Path(directory)
            (site / "spectra").mkdir()
            (site / teaching.DATA).write_text(teaching.canonical(self.payload), encoding="utf-8", newline="\n")
            with self.assertRaisesRegex(ValueError, "Partial teaching output"):
                teaching.validate(site)
            (site / teaching.PAGE).write_text(self.html, encoding="utf-8", newline="\n")
            with patch.object(teaching, "build_payload", return_value=self.payload) as reconstruct:
                teaching.validate(site)
                reconstruct.assert_called_once_with(site)
                changed = copy.deepcopy(self.payload)
                changed["cases"][0]["saved_trace"]["trace"]["preamp_V"][1] += 0.001
                # A self-reported hash does not authorize changed waveform samples.
                changed["provenance"]["generator_sha256"]["tools/teaching_examples.html"] = "0" * 64
                (site / teaching.DATA).write_text(teaching.canonical(changed), encoding="utf-8", newline="\n")
                with self.assertRaisesRegex(ValueError, "samples or source bindings changed"):
                    teaching.validate(site)
                (site / teaching.DATA).write_text(teaching.canonical(self.payload), encoding="utf-8", newline="\n")
                (site / teaching.PAGE).write_text(self.html.replace("Saved analog preamp", "Invented preamp"), encoding="utf-8", newline="\n")
                with self.assertRaisesRegex(ValueError, "rendering changed"):
                    teaching.validate(site)

    def test_page_is_offline_with_shared_renderer_and_bounded_layout(self):
        self.assertNotIn("__TEACHING_DATA_JSON__", self.html)
        self.assertNotIn("__FOCUSED_PLOTS_JS__", self.html)
        self.assertNotRegex(self.html, r"<script[^>]+\bsrc=")
        self.assertNotRegex(self.html, r"<a\b[^>]*\bdownload\b")
        self.assertIn("grid-template-columns:repeat(2,minmax(0,1fr))", self.html)
        self.assertIn("@media(max-width:750px)", self.html)
        self.assertIn("Original native charge stays negative", self.html)
        self.assertIn("Time since selected group origin", self.html)
        embedded = re.search(r'<script id="teaching-data" type="application/json">(.*?)</script>',
                             self.html, re.S).group(1)
        self.assertEqual(json.loads(embedded), self.payload)

    def test_actual_template_switches_all_six_cases_and_preserves_sparse_analog(self):
        self.assertTrue(NODE, "Set TEACHING_NODE to the existing Node executable")
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", self.html, re.S)
        app = scripts[-1]
        runtime = r'''
const assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const input=JSON.parse(fs.readFileSync(0,"utf8"));
class Element{constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.style={};this.textContent="";this.selectedIndex=0;this.open=false;this.hidden=false;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}setAttribute(name,value){this.attributes[name]=String(value);}}
const nodes=new Map(),document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element("div"));return nodes.get(id);},createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
document.getElementById("teaching-data").textContent=JSON.stringify(input.payload);
const context=vm.createContext({document});vm.runInContext(input.renderer,context);
const captured=[],originalDraw=context.SavedFocusPlots.draw;
context.SavedFocusPlots.draw=(host,panels,clock)=>{captured.push({panels,clock});originalDraw(host,panels,clock);};
vm.runInContext(input.app,context);
const walk=node=>[node,...node.children.flatMap(walk)];
for(let i=0;i<input.payload.cases.length;i++){
 const selector=document.getElementById("example-select");selector.selectedIndex=i;selector.onchange();
 const item=input.payload.cases[i],panels=captured.at(-1).panels,host=document.getElementById("plots");
 assert.equal(host.children.length,4);
 assert.equal(document.getElementById("error").textContent,"");
 assert.equal(captured.at(-1).clock,"Time since selected group origin · ns");
 assert.deepEqual(Array.from(panels[2].time_ns),item.saved_trace.trace.time_ns);
 assert.deepEqual(Array.from(panels[2].values),item.saved_trace.trace.preamp_V);
 assert.deepEqual(Array.from(panels[3].values),item.saved_trace.trace.shaped_V);
 assert.equal(panels[2].full_end_ns,item.saved_trace.trace.time_ns.at(-1));
 assert.equal(panels[2].focus_series,undefined);
 assert.equal(panels[1].current_from_charge.readout_end_ns,item.pulse.readout.readout_end_ns);
 const native=item.native_charge.induced_equivalent_energy_keV,factor=input.payload.models[item.model].wiring.factor;
 assert.deepEqual(Array.from(panels[1].current_from_charge.values),native.map(v=>v*factor));
 const preamp=host.children[2],button=walk(preamp).find(n=>n.tag==="button"&&n.textContent==="Full saved window");button.onclick();
 const range=walk(preamp).find(n=>n.tag==="small");assert.match(range.textContent,/600 displayed samples/);
 assert.equal(document.getElementById("case-report").href,"../results/cs137-10k/"+item.model+"/charge-readout.html");
 document.getElementById("exact-details").open=true;document.getElementById("exact-details").ontoggle();
 const exact=JSON.parse(document.getElementById("exact-json").textContent);assert.equal(exact.selected_case.event_id,item.event_id);assert.equal(exact.selected_case.model,item.model);
}
console.log("six selections / 24 plots / exact sparse preamp and shaper / fixed wiring passed");
'''
        result = subprocess.run([NODE, "-e", runtime], input=json.dumps({
            "payload": self.payload, "app": app,
            "renderer": (ROOT / "tools/focused_plots.js").read_text(encoding="utf-8")}),
            text=True, encoding="utf-8", capture_output=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
