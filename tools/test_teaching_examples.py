"""Focused saved-data and rendering contracts for the curated teaching reader."""
import copy
import hashlib
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
import gzip

import teaching_examples as teaching
import result_web_delivery as delivery
from site_canonical_views import canonical_html

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "docs"
NODE = os.environ.get("TEACHING_NODE") or shutil.which("node")


def source_path(name):
    path = SITE / name
    if not path.is_file() and name.startswith(delivery.PREFIX + "/"):
        path = ROOT / ".local/ring-publication-v1/web-bundle" / name.removeprefix(delivery.PREFIX + "/")
    return path


class TeachingExamplesTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Published teaching science is independently sealed even though two
        # large source ZIPs intentionally stay outside the public tree.
        cls.payload = json.loads((SITE / teaching.DATA).read_bytes())
        science = copy.deepcopy(cls.payload)
        science["provenance"].pop("generator_sha256")
        if hashlib.sha256(teaching.canonical(science).encode()).hexdigest() != delivery.TEACHING_SCIENCE_SHA256:
            raise AssertionError("Accepted teaching science changed")
        cls.payload["provenance"]["generator_sha256"] = dict(teaching.LOADED_GENERATORS)
        cls.presentation = teaching.presentation(SITE, cls.payload)
        cls.html = teaching.render(cls.payload, SITE)

    def test_six_cases_equal_original_saved_ledgers_and_traces(self):
        self.assertEqual([(c["model"], c["event_id"], c["group_id"])
                          for c in self.payload["cases"]],
                         [(m, e, g) for m, e, g, _, _ in teaching.SELECTION])
        for model, folder in teaching.FOLDERS.items():
            selected = [c for c in self.payload["cases"] if c["model"] == model]
            archive_path = source_path(folder + "/ledgers.zip")
            self.assertEqual(teaching.sha(archive_path), teaching.SOURCE_SHA256[folder + "/ledgers.zip"])
            with zipfile.ZipFile(archive_path) as archive:
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

    def test_deposit_positions_are_exact_detector_local_and_inside_frozen_crystal(self):
        def in_section(r, z, polygon):
            inside = False
            for (x1, y1), (x2, y2) in zip(polygon, polygon[1:] + polygon[:1]):
                dx, dy = x2-x1, y2-y1
                if dx or dy:
                    t = max(0, min(1, ((r-x1)*dx + (z-y1)*dy)/(dx*dx+dy*dy)))
                    if math.hypot(r-(x1+t*dx), z-(y1+t*dy)) < 1e-7:
                        return True
                if (y1 > z) != (y2 > z) and r < (x2-x1)*(z-y1)/(y2-y1)+x1:
                    inside = not inside
            return inside
        for case in self.payload["cases"]:
            model = case["model"]
            prefix = "examples/cs137-10k-rings" if model in ("GeRC02", "KMRC01_candidate") else "examples/cs137-10k-hits"
            manifest = json.loads((SITE / prefix / "manifest.json").read_bytes())
            scene = json.loads((SITE / prefix / manifest["models"][model]["scene"]).read_bytes())
            transform = scene["coordinate_transform"]
            self.assertEqual(transform["definition"], "x_global_mm=R*x_local_mm+t")
            rotation, shift = transform["rotation_local_to_global"], transform["translation_global_mm"]
            crystal = self.presentation[model]["crystal"]
            polygon = list(zip(crystal["r_mm"], crystal["z_mm"]))
            group_rows = set(case["pulse"]["raw_row_indices"])
            for row in case["truth"]["steps"]:
                shifted = [1000*v-s for v, s in zip(row["global_position_m"], shift)]
                local = [sum(rotation[j][i]*shifted[j] for j in range(3)) for i in range(3)]
                for actual, expected in zip(row["position_mm"], local):
                    self.assertAlmostEqual(actual, expected, delta=1e-10)
                if row["raw_row_index"] in group_rows and row["energy_keV"] > 0:
                    x, y, z = row["position_mm"]
                    self.assertTrue(in_section(math.hypot(x, y), z, polygon),
                                    f"{model}/{case['event_id']}/{row['raw_row_index']} outside crystal")

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

    def test_all_six_examples_link_to_the_same_saved_3d_pulse_group(self):
        saved = {}
        for case in self.payload['cases']:
            model = case['model']
            if model not in saved:
                folder = SITE / ('examples/cs137-10k-rings' if model in ('GeRC02', 'KMRC01_candidate')
                                 else 'examples/cs137-10k-hits')
                manifest = json.loads((folder / 'manifest.json').read_text(encoding='utf-8'))
                selected = folder / manifest['models'][model]['selected']
                saved[model] = json.loads(gzip.decompress(selected.read_bytes()))
            primary = next(e for e in saved[model]['evidence'] if e['event_id'] == case['event_id'])
            group = next(g for g in primary['groups'] if g['group_id'] == case['group_id'])
            self.assertEqual(group['ge_raw_row_indices'], case['pulse']['raw_row_indices'])
            self.assertAlmostEqual(group['ge_energy_keV'], case['pulse']['deposited_energy_keV'], delta=2e-10)

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
            with patch.object(teaching, "build_payload", return_value=self.payload) as reconstruct, patch.object(
                    teaching, "presentation", return_value=self.presentation):
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

    def test_previous_navigation_admission_still_reconstructs_science(self):
        with tempfile.TemporaryDirectory(dir=ROOT / ".local", prefix="teaching-contract-") as directory:
            site = Path(directory)
            (site / "spectra").mkdir()
            previous = copy.deepcopy(self.payload)
            previous["provenance"]["generator_sha256"] = {"previous": "0" * 64}
            data, page = teaching.canonical(previous).encode(), b"exact previous display"
            (site / teaching.DATA).write_bytes(data)
            (site / teaching.PAGE).write_bytes(page)
            hashes = tuple(hashlib.sha256(b).hexdigest() for b in (data, page))
            with patch.object(teaching, "PREVIOUS_DISPLAY", hashes), patch.object(
                    teaching, "build_payload", return_value=self.payload), patch.object(
                    teaching, "presentation", return_value=self.presentation):
                self.assertEqual(teaching.validate(site)["generators"], previous["provenance"]["generator_sha256"])
                changed = copy.deepcopy(self.payload)
                changed["cases"][0]["saved_trace"]["trace"]["preamp_V"][1] += 0.001
                with patch.object(teaching, "build_payload", return_value=changed):
                    with self.assertRaisesRegex(ValueError, "scientific content changed"):
                        teaching.validate(site)
                (site / teaching.PAGE).write_bytes(page + b"changed")
                with self.assertRaisesRegex(ValueError, "source bindings changed"):
                    teaching.validate(site)

    def test_actual_template_switches_all_six_cases_and_preserves_sparse_analog(self):
        self.assertTrue(NODE, "Set TEACHING_NODE to the existing Node executable")
        canonical = canonical_html(self.html.encode(), teaching.PAGE, "learn/signals/index.html").decode()
        scripts = re.findall(r"<script(?:\s[^>]*)?>(.*?)</script>", canonical, re.S)
        app = scripts[-1]
        runtime = r'''
const assert=require("node:assert/strict"),vm=require("node:vm"),fs=require("node:fs");
const input=JSON.parse(fs.readFileSync(0,"utf8"));
class Element{constructor(tag){this.tag=tag;this.children=[];this.attributes={};this.style={};this.textContent="";this.selectedIndex=0;this.open=false;this.hidden=false;}append(...nodes){this.children.push(...nodes);}replaceChildren(...nodes){this.children=[...nodes];}setAttribute(name,value){this.attributes[name]=String(value);}}
const nodes=new Map(),document={getElementById(id){if(!nodes.has(id))nodes.set(id,new Element("div"));return nodes.get(id);},createElement:tag=>new Element(tag),createElementNS:(_,tag)=>new Element(tag)};
document.getElementById("teaching-data").textContent=JSON.stringify(input.payload);
document.getElementById("teaching-presentation").textContent=JSON.stringify(input.presentation);
const listeners=new Map(),location={pathname:'/learn/signals/index.html',search:'',hash:''};
const history={pushState(_,__,url){location.search=new URL(url,'https://test.invalid').search;},replaceState(_,__,url){location.search=new URL(url,'https://test.invalid').search;}};
const context=vm.createContext({document,URLSearchParams,location,history,addEventListener:(name,fn)=>listeners.set(name,fn)});context.window=context;vm.runInContext(input.renderer,context);
const captured=[],originalDraw=context.SavedFocusPlots.draw;
context.SavedFocusPlots.draw=(host,panels,clock)=>{captured.push({panels,clock});originalDraw(host,panels,clock);};
vm.runInContext(input.app,context);
assert.equal(document.getElementById('example-select').selectedIndex,0);
assert.equal(document.getElementById('stage-select').value,'deposits');
assert.equal(document.getElementById('deposit-figure').hidden,false);
assert.equal(document.getElementById('deposit-plot').children[0].tag,'svg');
assert.equal(document.getElementById('deposit-rows').children.length,0);
const walk=node=>[node,...node.children.flatMap(walk)];
const stageNames=['deposits','charge','current','preamp','shaper','adc'];
let downloadChecks=0,stageChecks=0;
for(let i=0;i<input.payload.cases.length;i++){
 const selector=document.getElementById("example-select");selector.selectedIndex=i;selector.onchange();
 const item=input.payload.cases[i],panels=captured.at(-1).panels,host=document.getElementById("plots");
 assert.equal(host.children.length,4);
 assert.equal(document.getElementById("error").textContent,"");
 assert.equal(document.getElementById('case-explanation').textContent.includes('661.6572831606164'),false);
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
 const report=new URL(document.getElementById("case-report").href,'https://test.invalid/learn/signals/index.html');
 assert.equal(report.pathname,"/results/cs137-10k/"+item.model+"/charge-readout.html");
 assert.equal(report.searchParams.get('study'),'cs137-10k');assert.equal(report.searchParams.get('event'),String(item.event_id));assert.equal(report.searchParams.get('group'),String(item.group_id));
 assert.equal(document.getElementById('case-3d').href.includes('event='+item.event_id+'&group='+item.group_id+'&view=positive'),true);
 const anchors=walk(document.getElementById('download-links')).filter(n=>n.tag==='a');
 assert.ok(anchors.length>=4);
 for(const anchor of anchors){
  const href=new URL(anchor.href,'https://test.invalid/learn/signals/index.html');
  assert.ok(input.publishedFiles.includes(href.pathname.slice(1)),'Unpublished runtime download: '+href.pathname);
  assert.ok(!input.omitted.includes(href.pathname.slice(1)),'Omitted archive linked: '+href.pathname);downloadChecks++;
 }
 for(const file of ['run.json','histograms.json','signals.csv'])assert.ok(anchors.some(a=>a.href.endsWith('/'+file)));
 assert.ok(anchors.some(a=>/\/scalars\.(csv|jsonl)$/.test(a.href)));
 assert.equal(anchors.some(a=>a.href.endsWith('/ledgers.zip')),['AK02','SAP22'].includes(item.model));
 assert.match(document.getElementById('archive-note').textContent,['AK02','SAP22'].includes(item.model)?/complete source ZIP is published/:/retained locally and is not published/);
 for(let stageIndex=0;stageIndex<stageNames.length;stageIndex++){
  const stage=stageNames[stageIndex];document.getElementById('stage-'+stage).onclick();
  assert.equal(document.getElementById('stage-select').value,stage);
  const visible=document.getElementById('plots').children.filter(n=>!n.hidden).length+Number(!document.getElementById('deposit-figure').hidden)+Number(!document.getElementById('adc-figure').hidden);
  assert.equal(visible,1,'One main plot for '+item.model+'/'+stage);
  assert.equal(stageNames.filter(s=>document.getElementById('stage-'+s).attributes['aria-pressed']==='true').length,1);
  assert.equal(document.getElementById('stage-previous').disabled,stageIndex===0);
  assert.equal(document.getElementById('stage-next').disabled,stageIndex===5);
  assert.equal(new URLSearchParams(location.search).get('stage'),stage);stageChecks++;
 }
 document.getElementById('stage-previous').onclick();assert.equal(document.getElementById('stage-select').value,'shaper');
 document.getElementById('stage-deposits').onclick();document.getElementById('stage-next').onclick();assert.equal(document.getElementById('stage-select').value,'charge');
 document.getElementById('stage-deposits').onclick();
 const plotted=walk(document.getElementById('deposit-plot')).filter(n=>n.tag==='circle').map(n=>Number(n.attributes['data-raw-row'])).sort((a,b)=>a-b);
 const groupRows=new Set(item.pulse.raw_row_indices),expectedRows=item.truth.steps.filter(row=>groupRows.has(row.raw_row_index)&&row.energy_keV>0).map(row=>row.raw_row_index).sort((a,b)=>a-b);
 assert.deepEqual(plotted,expectedRows);
 document.getElementById("exact-details").open=true;document.getElementById("exact-details").ontoggle();
 const exact=JSON.parse(document.getElementById("exact-json").textContent);assert.equal(exact.selected_case.event_id,item.event_id);assert.equal(exact.selected_case.model,item.model);
 const saved=new URLSearchParams(location.search);assert.equal(saved.get('event'),String(item.event_id));assert.equal(saved.get('group'),String(item.group_id));
}
location.search='?study=cs137-10k&model=GeRC02&variant=GeRC02_Li50min&event=69&group=0&stage=shaper';listeners.get('popstate')();
assert.equal(document.getElementById('example-select').selectedIndex,3);assert.equal(document.getElementById('stage-select').value,'shaper');assert.equal(document.getElementById('content').hidden,false);
listeners.get('pageshow')();assert.equal(document.getElementById('example-select').selectedIndex,3);
location.search='?study=cs137-10k&model=AK02&variant=AK02&event=698&group=0';listeners.get('popstate')();assert.equal(document.getElementById('content').hidden,true);assert.match(document.getElementById('error').textContent,/No curated teaching waveform/);
location.search='?study=cs137-10k&model=GeRC02&variant=GeRC02_Li30min&event=61&group=0';listeners.get('popstate')();assert.equal(document.getElementById('content').hidden,true);assert.match(document.getElementById('error').textContent,/variant is unavailable/);
assert.equal(stageChecks,36);assert.equal(downloadChecks,27);
console.log("six selections / 36 stage transitions / 27 actual published download choices / exact sparse signals and local deposit rows passed");
'''
        result = subprocess.run([NODE, "-e", runtime], input=json.dumps({
            "payload": self.payload, "presentation": self.presentation, "app": app,
            "publishedFiles": [path.relative_to(SITE).as_posix() for path in SITE.rglob("*") if path.is_file()],
            "omitted": [delivery.PREFIX + "/" + name for name in delivery.OMITTED],
            "renderer": (ROOT / "tools/focused_plots.js").read_text(encoding="utf-8")}),
            text=True, encoding="utf-8", capture_output=True, check=False, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
