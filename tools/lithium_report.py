"""Export completed diagnose_lithium.jl schema 1; no solver or raw cache access."""
import argparse
import csv
import hashlib
import html
import io
import json
import math
import re
from pathlib import Path
import statistics

import pipeline_demo as common

ROOT = Path(__file__).resolve().parents[1]
FILES = ("report.json", "endpoint-audit.csv", "depth-scan.csv", "profiles.csv")
HEADERS = dict(zip(FILES[1:], (
    "model,event_id,raw_row_index,species,energy_keV,original_keV,no_trapping_keV,conditional_remainder_keV,endpoint_W,end_time_ns,region,geometric_contact,at_step_limit,exactly_zero_E,stationary,source_match",
    "grid_case,depth_mm,dt_ns,horizon_ns,seed,n,diffusion,mean,sem,no_trapping_mean,no_trapping_sem,integrity_pass",
    "grid_case,depth_mm,E_V_cm,W,donor_cm3,net_cm3,mu_e_m2_V_s,mu_h_m2_V_s,D_e_m2_s,D_h_m2_s,nearest_bits,impurity_scale,region")))
PINS = {"AK02": "793de4cc598a3e26d375525e683be1bc2072e117d1c6b8003f6cdcffc9925dfa",
        "SAP22": "614c72f31a5a84b82c69b0b11f6f0657e87d94f746312c151f9a08cd00ba3dc3"}
DEPTHS = [.1, .3, .45, .50, .55, .60, .65, .8, 1.0]
SEEDS = [2609261, 2609262, 2609263]
GRIDS = [["baseline", .05, 4], ["contrast50", .05, 8], ["contrast25", .025, 8]]
FLAGS = ("geometric_contact", "at_step_limit", "exactly_zero_E", "stationary", "n_type", "nearest_undepleted")
GRID_FILES = {"transition-profiles.csv": "profiles.csv", "transition-comparisons.csv": "smallcomparisons.csv"}
AXES_FILES = {"axes-profiles.csv": "profiles.csv", "axes-comparisons.csv": "comparisons.csv"}
AXES_CASES = ("min50", "min25", "g22_from50", "g22_from25", "g11", "g12", "g21")
AXES_PAIRS = (("g11", "g21"), ("g12", "g22_from50"), ("g11", "g12"), ("g21", "g22_from50"))
HEADERS.update({"axes-profiles.csv": "case,stage,depth_mm,Ex_V_cm,Ey_V_cm,Ez_V_cm,magnitude_V_cm,V,alpha,pointbits,netdensity_cm3",
                "axes-comparisons.csv": "reference,candidate,normalized_E,onset1_separation_upper_mm,max_local_source_difference_cm3,accepted_inputs,passed"})
HEADERS.update({"transition-profiles.csv": "case,stage,depth_mm,E_V_cm,W,alpha,point_bits,net_impurity_cm3",
                "transition-comparisons.csv": "reference,candidate,normalized_E,onset0_shift_mm,onset1_shift_mm,max_W,passed"})
require = common.require
escape = lambda value: html.escape(str(value), quote=True)

TEMPLATE = """<!doctype html><html lang="en"><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Native Li diagnostics</title>
<style>body{font:16px/1.55 system-ui,sans-serif;color:#172d3d;background:#f4f7fa;margin:auto;padding:24px;max-width:1150px}
h1,h2{line-height:1.2}a{color:#005fa3}section{background:white;padding:20px;margin:20px 0;border-radius:12px}
.warning{border-left:6px solid #bd4b12;background:#fff3e9;padding:16px}.plots{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:18px}
svg{width:100%;height:auto}table{border-collapse:collapse;width:100%;font-size:14px}td,th{padding:8px;text-align:left;border-bottom:1px solid #ccd5de}
.scroll{overflow:auto}pre{white-space:pre-wrap;overflow-wrap:anywhere;font-size:12px}small{color:#40576a}</style>
<body><h1>Native lithium-region diagnostics</h1>__BODY__</body></html>"""


def finite_tree(value):
    if isinstance(value, dict):
        for v in value.values():
            finite_tree(v)
    elif isinstance(value, list):
        for v in value:
            finite_tree(v)
    elif isinstance(value, float):
        require(math.isfinite(value), "nonfinite value")


def hash_map(base, hashes):
    require(isinstance(hashes, dict) and hashes, "missing source hashes")
    for name, digest in hashes.items():
        require(common.sha256(common.relative_file(base, name)) == digest, "source hash mismatch: " + name)


def digest_map(hashes):
    require(isinstance(hashes, dict) and hashes, "missing artifact hashes")
    for name, digest in hashes.items():
        common.relative_file(ROOT, name)  # Validate portable identity, without opening raw inputs.
        require(isinstance(digest, str) and len(digest) == 64 and all(c in "0123456789abcdef" for c in digest), "invalid digest")


def endpoints(rows):
    result = {"deposits": len(rows), "energy_keV": sum(r["energy_keV"] for r in rows),
              "species_counts": {}, "zero_E_and_stationary_counts": {}}
    for s in ("electron", "hole"):
        result["species_counts"][s] = {k: sum(r["endpoints"][s]["flags"][k] for r in rows) for k in FLAGS}
        result["zero_E_and_stationary_counts"][s] = sum(r["endpoints"][s]["flags"]["exactly_zero_E"] and r["endpoints"][s]["flags"]["stationary"] for r in rows)
    for name, field in (("conditional", "conditional_remainder_keV"), ("absolute_component", "absolute_component_sum_keV")):
        result[f"energy_weighted_{name}_fraction"] = sum(r[field] for r in rows) / result["energy_keV"] if rows else None
    return result


def check_rows(rows):
    for r in rows:
        require(r["ramo_pass"] is True and r["path_integrity_pass"] is True, "Ramo/path integrity failed")
        require(r["energy_keV"] > 0, "invalid parcel/deposit energy")
        require(set(r["endpoints"]) == {"electron", "hole"}, "missing endpoint species")
        for endpoint in r["endpoints"].values():
            require(endpoint["noncontact_outer_points"] == 0, "path outside semiconductor/contact")
            require(all(type(endpoint["flags"][k]) is bool for k in FLAGS), "invalid endpoint flags")
        require(abs(r["ramo_error"]) <= 1e-10, "Ramo identity failed")


def cloud_key(c):
    return tuple(c[k] for k in ("grid_case", "depth_mm", "dt_ns", "horizon_ns", "seed", "diffusion"))


def validate(report):
    """Fail closed on incomplete work/integrity; sensitivity is diagnostic data."""
    finite_tree(report)
    require(report["schema_version"] == 1 and report["kind"] == "native_lithium_diagnostics" and
            report["status"] == "completed_diagnostics_only", "need completed diagnostics schema 1")
    phase = report["phase"]
    require(phase in ("all", "audit", "depth"), "unknown phase")
    require(set(report["source_hashes"]) == {"diagnose_lithium.jl", "test_lithium.jl", "diagnose_collection.jl"}, "missing diagnostic sources")
    hash_map(ROOT / "simulation", report["source_hashes"])
    sources = report["producer_sources"]
    require(all("simulation/" + n in sources for n in ("run.jl", "replay.jl", "readout.jl", "readout_demo.json", "Project.toml", "Manifest.toml")), "missing producer physical inputs")
    hash_map(ROOT, sources)
    digest_map(report["input_artifacts"])
    digest_map({"run.json": report["input_run_sha256"]})
    digest_map(report["sdk_source_pins"])
    require(all(f"{m}/{n}" in report["input_artifacts"] for m in PINS for n in
                ("transport/events.json", "charge/run.json", "charge/signals.csv", "readout/run.json")), "missing input identity")
    for model, digest in PINS.items():
        require(sources[f"models/{model}.yaml"] == digest == common.sha256(ROOT / "models" / (model + ".yaml")), "model pin mismatch")
    work = report["fixed_work"]
    expected = dict(depths_mm=DEPTHS, seeds=SEEDS, grid_cases=GRIDS, parcels_per_seed=32,
                    max_primaries_per_model=100, max_positive_deposits_per_model=2048,
                    diffusive_clouds=63, no_diffusion_controls=9, default_dt_ns=2, default_horizon_ns=5000)
    require(all(work[k] == v for k, v in expected.items()), "fixed_work differs from supported producer schedule")
    wanted = {("AK02", "baseline")}
    if phase != "depth":
        wanted.add(("SAP22", "baseline"))
    if phase != "audit":
        wanted.update(("AK02", g) for g in ("contrast50", "contrast25"))
    cases = report["cases"]
    require(len(cases) == len(wanted) and {(i["model"], i["case"]) for i in cases} == wanted, "case census mismatch")
    expected_clouds = set()
    if phase != "audit":
        expected_clouds.update(("baseline", d, 2, 5000, s, True) for d in DEPTHS for s in SEEDS)
        expected_clouds.update(("baseline", d, 2, 5000, SEEDS[0], False) for d in DEPTHS)
        expected_clouds.update(("baseline", d, dt, h, s, True) for d in (.3, .55, .8) for s in SEEDS for dt, h in ((4, 5000), (2, 10000)))
        expected_clouds.update((g, d, 2, 5000, s, True) for g in ("contrast50", "contrast25") for d in (.50, .55, .60) for s in SEEDS)
    clouds = [c for i in cases for c in i.get("clouds", [])]
    require(len(clouds) == len(expected_clouds) and {cloud_key(c) for c in clouds} == expected_clouds, "cloud census mismatch")
    for item in cases:
        require(item["model_sha256"] == PINS[item["model"]], "selected model mismatch")
        _, spacing, rechecks = next(g for g in GRIDS if g[0] == item["case"])
        require(item["min_grid_mm"] == spacing and item["rechecks"] == rechecks, "grid settings mismatch")
        if phase != "depth" and item["case"] == "baseline":
            events = item["events"]
            require(item["integrity_pass"] is True and item["differences"] == [], "audit integrity failed")
            require(len(events) == item["summary"]["primary_count"] == 100 and len({e["event_id"] for e in events}) == 100, "audit requires 100 unique primaries per model")
            require(all(e["source_match"] is True and all(r["source_match"] is True for r in e["deposits"]) for e in events), "source replay mismatch")
            for e in events:
                positive = [r for r in e["raw_steps"] if r["energy_keV"] > 0]
                require([(r["raw_row_index"], r["energy_keV"]) for r in positive] == [(r["raw_row_index"], r["energy_keV"]) for r in e["deposits"]], "raw deposit census mismatch")
                saved = e["source_charge_report"]
                require(len(e["raw_steps"]) == saved["raw_rows"] and len(positive) == saved["charge_deposits"] == len(saved["steps"]), "producer event census mismatch")
            rows = [r for e in events for r in e["deposits"]]
            require(len(rows) == item["summary"]["deposits"] <= work["max_positive_deposits_per_model"], "audit deposit census mismatch")
            require(sum(not e["deposits"] for e in events) == item["summary"]["zero_deposit_primaries"], "zero census mismatch")
            check_rows(rows)
        else:
            require(not item.get("events"), "unexpected audit phase data")
        for c in item.get("clouds", []):
            require(c["grid_case"] == item["case"] and c["integrity_pass"] is True, "cloud integrity/case mismatch")
            require(c["self_repulsion"] is False and c["end_drift_when_no_field"] is (not c["diffusion"]), "cloud physics flags changed")
            rows = c["parcels"]
            require(len(rows) == c["numerical_parcels"] == (32 if c["diffusion"] else 1), "parcel census mismatch")
            require([r["parcel_id"] for r in rows] == list(range(1, len(rows) + 1)), "parcel IDs changed")
            require(c["total_energy_keV"] == sum(r["energy_keV"] for r in rows) == 1 and all(r["energy_keV"] == 1 / len(rows) for r in rows), "parcel weights changed")
            check_rows(rows)
            for stats, key in (("original_stats", "original_fraction"), ("no_trapping_stats", "no_trapping_fraction")):
                values = [r[key] for r in rows]
                require(c[stats]["n"] == len(rows) and math.isclose(c[stats]["mean"], statistics.mean(values), abs_tol=1e-12, rel_tol=1e-12), "cloud mean mismatch")
                sem = statistics.stdev(values) / math.sqrt(len(values)) if len(values) > 1 else None
                require(c[stats]["sem"] is None if sem is None else math.isclose(c[stats]["sem"], sem, abs_tol=1e-12, rel_tol=1e-12), "cloud SEM mismatch")
    comparisons = report.get("sensitivities", [])
    expected_comparisons = []
    by_key = {cloud_key(c): c for c in clouds}
    for b in clouds:
        g, d, dt, h, s, diffusion = cloud_key(b)
        if not diffusion or not (g == "contrast25" or g == "baseline" and (dt != 2 or h != 5000)):
            continue
        a = by_key[("contrast50" if g == "contrast25" else "baseline", d, 2, 5000, s, True)]
        for signal in ("original_stats", "no_trapping_stats"):
            delta = abs(a[signal]["mean"] - b[signal]["mean"])
            gate = max(.03, 4 * math.sqrt(a[signal]["sem"] ** 2 + b[signal]["sem"] ** 2))
            expected_comparisons.append(dict(kind="grid" if g == "contrast25" else "time_step" if dt == 4 else "horizon", depth_mm=d, seed=s, signal=signal, absolute_difference=delta, prospective_gate=gate, passed=delta <= gate))
    require(len(comparisons) == len(expected_comparisons), "sensitivity census mismatch")
    for actual, expected in zip(comparisons, expected_comparisons):
        require(type(actual["passed"]) is bool, "invalid sensitivity flag")
        require(all(math.isclose(actual[k], v, abs_tol=1e-12, rel_tol=1e-12) if type(v) is float else actual[k] == v for k, v in expected.items()), "sensitivity record mismatch")
    if phase != "audit":
        require(report["sensitivity_all_passed"] is all(c["passed"] for c in comparisons), "sensitivity overall flag mismatch")
    return clouds


def csv_rows(raw, name=None):
    reader = csv.DictReader(io.StringIO(raw.decode("utf-8")))
    rows = list(reader)
    require(reader.fieldnames and len(set(reader.fieldnames)) == len(reader.fieldnames), "invalid CSV header")
    if name is not None:
        require(reader.fieldnames == HEADERS[name].split(','), "CSV schema mismatch: " + name)
    for row in rows:
        require(None not in row and all(v is not None for v in row.values()), "malformed CSV")
        for value in row.values():
            try:
                number = float(value)
            except ValueError:
                continue
            require(math.isfinite(number), "nonfinite CSV")
    return rows


def check_csv(actual, expected):
    require(len(actual) == len(expected), "CSV row count mismatch")
    for a, b in zip(actual, expected):
        for key, value in b.items():
            cell = a[key]
            require(cell == str(value).lower() if isinstance(value, bool) else
                    float(cell) == value if isinstance(value, (int, float)) else cell == str(value), "CSV/report mismatch: " + key)


def seed_equivalence(clouds):
    """Additional post-run paired-seed diagnostic, not the original loose screen."""
    index = {cloud_key(c)[:5]: c for c in clouds if c["diffusion"]}
    groups = {}
    for key, b in index.items():
        grid, depth, dt, horizon, seed = key
        if grid == "contrast25":
            kind, reference = "grid", "contrast50"
        elif grid == "baseline" and (dt != 2 or horizon != 5000):
            kind, reference = ("time_step" if dt != 2 else "horizon"), "baseline"
        else:
            continue
        a = index[(reference, depth, 2, 5000, seed)]
        for signal in ("original_stats", "no_trapping_stats"):
            groups.setdefault((kind, depth, signal), []).append((seed, b[signal]["mean"] - a[signal]["mean"]))
    result = []
    t95 = math.sqrt(2 * .95**2 / (1 - .95**2))  # Exact two-degree-of-freedom t quantile.
    for (kind, depth, signal), samples in sorted(groups.items()):
        require(sorted(seed for seed, _ in samples) == SEEDS, "equivalence needs the three fixed seeds")
        differences = [value for _, value in sorted(samples)]
        mean = statistics.mean(differences)
        sem = statistics.stdev(differences) / math.sqrt(3)
        interval = [mean - t95 * sem, mean + t95 * sem]
        result.append(dict(kind=kind, depth_mm=depth, signal=signal, signed_seed_differences=differences,
                           mean_difference=mean, seed_sem=sem, approximate_t95=interval,
                           inside_0p02=interval[0] >= -.02 and interval[1] <= .02))
    return result


def summarize(report, clouds, csv_data, hashes):
    scan = [dict(zip(("grid_case", "depth_mm", "dt_ns", "horizon_ns", "seed", "diffusion"), cloud_key(c)),
                 n=c["numerical_parcels"], mean=c["original_stats"]["mean"], sem=c["original_stats"]["sem"] if c["diffusion"] else "nothing",
                 no_trapping_mean=c["no_trapping_stats"]["mean"], no_trapping_sem=c["no_trapping_stats"]["sem"] if c["diffusion"] else "nothing", integrity_pass=True) for c in clouds]
    check_csv(csv_data["depth-scan.csv"], scan)
    audit_rows, audits, cases = [], [], []
    for i in report["cases"]:
        cases.append({k: v for k, v in i.items() if k not in ("events", "clouds", "grids", "checks", "differences", "summary")})
        if "events" in i:
            rows = [r for e in i["events"] for r in e["deposits"]]
            audits.append(dict(model=i["model"], primary_count=len(i["events"]), zero_deposit_primaries=sum(not e["deposits"] for e in i["events"]), **endpoints(rows)))
            for e in i["events"]:
                for r in e["deposits"]:
                    for species, endpoint in ((s, r["endpoints"][s]) for s in ("electron", "hole")):
                        audit_rows.append(dict(model=i["model"], event_id=e["event_id"], raw_row_index=r["raw_row_index"], species=species,
                            energy_keV=r["energy_keV"], original_keV=r["original_final_keV"], no_trapping_keV=r["no_trapping_final_keV"], conditional_remainder_keV=r["conditional_remainder_keV"],
                            endpoint_W=endpoint["weighting_potential"], end_time_ns=endpoint["end_time_ns"], region=endpoint["region"], source_match=r["source_match"], **{k: endpoint["flags"][k] for k in FLAGS[:4]}))
    check_csv(csv_data["endpoint-audit.csv"], audit_rows)
    profiles = csv_data["profiles.csv"]
    profile_cases = [i for i in cases if i["model"] == "AK02"]
    require(len(profiles) == 501 * len(profile_cases), "profile census mismatch")
    for i in profile_cases:
        rows = [r for r in profiles if r["grid_case"] == i["case"]]
        require(len(rows) == 501 and all(math.isclose(float(r["depth_mm"]), j * .002, abs_tol=1e-14) for j, r in enumerate(rows)), "profile depth grid mismatch")
    means = []
    for d in report["fixed_work"]["depths_mm"]:
        group = [c for c in clouds if cloud_key(c)[:4] == ("baseline", d, 2, 5000) and c["diffusion"]]
        if group:
            row = dict(depth_mm=d, n_seeds=len(group), per_seed=[dict(seed=c["seed"], original=c["original_stats"]["mean"], no_trapping=c["no_trapping_stats"]["mean"]) for c in group])
            for key in ("original", "no_trapping"):
                values = [s[key] for s in row["per_seed"]]
                row[key] = dict(mean=statistics.mean(values), seed_sem=statistics.stdev(values) / math.sqrt(len(values)))
            means.append(row)
    metadata = {k: report[k] for k in ("phase", "status", "input_run_sha256", "input_artifacts", "producer_sources", "source_hashes", "sdk_source_pins", "environment", "fixed_work", "units", "limitations", "runtime_s")}
    metadata.update(input_files_sha256=hashes, exporter_sha256=common.sha256(Path(__file__)), template_sha256=hashlib.sha256(TEMPLATE.encode()).hexdigest(),
                    serialization="json-compact-sorted-ascii-v1", provenance_scope="Four diagnostic artifacts checked here. Original producer artifact and SDK hashes are recorded identities verified by the producer; raw inputs/installed SDK are not reopened.",
                    canonical_parameters=dict(temperature_K=77, stored_temperature_K=78, bias_V={"AK02": 500, "SAP22": 700}, bulk_lifetime_ns=1000000, inactive_lifetime_ns=1000))
    return dict(schema_version=1, kind="lithium_static_summary", metadata=metadata, cases=cases, audit=audits,
                clouds=[{k: v for k, v in c.items() if k not in ("parcels", "mean_trace")} for c in clouds], seed_means=means,
                sensitivities=report.get("sensitivities", []), profiles=profiles,
                seed_equivalence=seed_equivalence(clouds))


def plot(series, ylabel, marker=None):
    """Data-scaled SVG, signed values retained; error bars are seed-to-seed SEM."""
    points = [p for _, _, _, data in series for p in data]
    if not points:
        return "<p>This phase did not run a depth scan.</p>"
    xmin, xmax = min(p[0] for p in points), max(p[0] for p in points)
    ymin, ymax = min(p[1] - p[2] for p in points), max(p[1] + p[2] for p in points)
    pad = (ymax - ymin) * .08 or .1
    ymin, ymax = ymin - pad, ymax + pad
    x = lambda v: 70 + 430 * (v - xmin) / (xmax - xmin or 1)
    y = lambda v: 260 - 210 * (v - ymin) / (ymax - ymin)
    out = [f'<svg viewBox="0 0 540 {340 + 20 * len(series)}" role="img" aria-label="{escape(ylabel)}"><title>{escape(ylabel)} versus radial depth</title>']
    for j in range(5):
        xv, yv = xmin + (xmax - xmin) * j / 4, ymin + (ymax - ymin) * j / 4
        out.append(f'<path d="M70 {y(yv)}H500" stroke="#dde4eb"/><text x="64" y="{y(yv)+4}" text-anchor="end" font-size="12">{yv:.3g}</text><text x="{x(xv)}" y="280" text-anchor="middle" font-size="12">{xv:.3g}</text>')
    out.append(f'<text x="70" y="25" font-size="14">{escape(ylabel)}</text><text x="280" y="306" text-anchor="middle">Radial depth (mm)</text>')
    if marker is not None:
        out.append(f'<path d="M{x(marker)} 45V260" stroke="#665" stroke-dasharray="3 5"/><text x="70" y="326" font-size="12">Compensation depth: {marker:.5g} mm (dotted)</text>')
    for j, (label, color, dashed, data) in enumerate(series):
        path = " ".join(f'{x(a)},{y(b)}' for a, b, _ in data)
        out.append(f'<polyline points="{path}" fill="none" stroke="{color}" stroke-width="2" stroke-dasharray="{ "6 4" if dashed else "none"}"/>')
        for a, b, sem in data:
            out.append(f'<path d="M{x(a)} {y(b-sem)}V{y(b+sem)}M{x(a)-3} {y(b-sem)}H{x(a)+3}M{x(a)-3} {y(b+sem)}H{x(a)+3}" stroke="{color}"/><circle cx="{x(a)}" cy="{y(b)}" r="2" fill="{color}"/>')
        out.append(f'<text x="70" y="{348+j*20}" fill="{color}" font-size="13">{escape(label)}</text>')
    return "".join(out) + "</svg>"


def table(headers, rows):
    return '<div class="scroll"><table><tr>' + ''.join(f'<th>{escape(h)}</th>' for h in headers) + '</tr>' + ''.join('<tr>' + ''.join(f'<td>{escape(v)}</td>' for v in row) + '</tr>' for row in rows) + '</table></div>'


def compact_grid(value):
    """Retain scalar histories; replace repeated native ticks with exact-data identities."""
    if isinstance(value, list):
        return [compact_grid(v) for v in value]
    if not isinstance(value, dict):
        return value
    result = {}
    if "ticks_m_rad_m" in value:
        require([len(a) for a in value["ticks_m_rad_m"]] == value["shape"], "transition grid shape mismatch")
    for k, v in value.items():
        if k in ("ticks_m_rad_m", "ticks_internal"):
            require(all(a and all(y > x for x, y in zip(a, a[1:])) for a in v), "invalid actual ticks")
            result[k + "_summary"] = dict(sha256_json=hashlib.sha256(common.public_json_text(v).encode()).hexdigest(),
                axes=[dict(count=len(a), first=a[0], last=a[-1], spacing_range=[min(b-a for a, b in zip(a, a[1:])), max(b-a for a, b in zip(a, a[1:]))] if len(a)>1 else None) for a in v])
        else:
            result[k] = compact_grid(v)
    return result


def validate_transition_provenance(p):
    hash_map(ROOT / "simulation", p["sources"])
    source = (ROOT / "simulation/diagnose_transition_grid.jl").read_text(encoding="utf-8")
    legacy = (ROOT / "simulation/diagnose_lithium.jl").read_text(encoding="utf-8")
    pairs = lambda text: dict(re.findall(r'"([^"\n]+)"\s*=>\s*"([0-9a-f]{64})"', text))
    project = pairs(source.split("const SOURCE_PINS=", 1)[1].split("const NATIVE_PINS=", 1)[0])
    native = pairs(source.split("const NATIVE_PINS=", 1)[1].split("const HISTORICAL_REPORT_SHA", 1)[0])
    native.update(pairs(legacy.split("const SDK_PINS=", 1)[1].split("require=", 1)[0]))
    require(project and native and set(p["sources"]) == set(project) | {"diagnose_transition_grid.jl", "test_transition_grid.jl"}, "transition source inventory")
    require(all(p["sources"][n] == h for n, h in project.items()) and
            all(p["native_sources"].get(n) == h for n, h in native.items()), "transition declared source identity")
    tree_match = re.search(r'const NATIVE_TREE_SHA="([0-9a-f]{64})"', source)
    if tree_match:
        prefixes = ("PotentialCalculation/", "Grids/", "Axes/", "ScalarPotentials/", "ElectricField/")
        inventory = {n: h for n, h in p["native_sources"].items() if n.startswith(prefixes)}
        digest_map(inventory)
        tree = hashlib.sha256("\n".join(sorted(n + " " + h for n, h in inventory.items())).encode()).hexdigest()
        require(tree == tree_match.group(1) == p["native_tree_sha256"] and
                set(p["native_sources"]) == set(native) | set(inventory), "transition native tree identity")
    else:
        require(p["native_sources"] == native, "transition declared native source inventory")
    hash_map(ROOT / "simulation", pairs(legacy.split("const PINNED=", 1)[1].split("const SDK_PINS=", 1)[0]))
    require(p["environment"]["project"] == "simulation/Project.toml" and p["environment"]["environment_manifest_sha256"] == common.sha256(ROOT / "simulation/Manifest.toml"), "transition environment")
    require(p["model_sha256"] == PINS["AK02"] == common.sha256(ROOT / "models/AK02.yaml"), "transition AK02 identity")


def validate_transition(g, raw):
    finite_tree(g)
    common.check_public(g)
    require(g["schema_version"] == 1 and g["kind"] == "AK02_native_transition_grid", "transition schema")
    require(g["status"] in ("baseline_only", "partial_nested_not_converged", "nested_blocked_baseline_defects_or_failure", "bounded_numerical_convergence"), "transition incomplete/blocked")
    held, p = g["held_settings"], g["provenance"]
    require(all(held[k] == v for k, v in dict(temperature_K=77, bias_V=500, precision="Float64", sor=1, threads=2, max_grid_mm=2, profile_relative_gate=.01, onset_gate_mm=.002).items()), "transition held settings/gates changed")
    require(held["limits"]["V"] == 5e-6 and held["limits"]["W"] == 1e-8 and all(held["limits"][k] > 0 for k in ("seconds", "points", "initial", "extra")), "transition native gates/budgets")
    validate_transition_provenance(p)
    require(g["reporter_test_sha256"] == common.sha256(Path(__file__).with_name("test_lithium_report.py")), "transition reporter tests changed")
    digest_map({"report.json": g["report_sha256"], **g["artifacts"]})
    require(set(g["artifacts"]) == set(GRID_FILES.values()), "transition artifact inventory")
    for public, original in GRID_FILES.items():
        require(hashlib.sha256(raw[public]).hexdigest() == g["artifacts"][original], "transition CSV hash mismatch")
        common.check_public(raw[public].decode("utf-8"))
    profiles, comparisons = [csv_rows(raw[n], n) for n in GRID_FILES]
    require(profiles and profiles == g["profiles"], "transition missing/changed profiles")
    cases = {c["case"]: c for c in g["cases"]}
    require(cases and len(cases) == len(g["cases"]), "transition case census")
    groups = {}
    for r in profiles:
        for k in ("depth_mm", "E_V_cm", "W", "alpha", "point_bits", "net_impurity_cm3"):
            require(math.isfinite(float(r[k])), "transition invalid profile field")
        require(r["case"] in cases and r["stage"] in ("initial", "continued", "final"), "transition unknown profile")
        groups.setdefault((r["case"], r["stage"]), []).append(r)
    require(set(groups) == {(n, s) for n, c in cases.items() for s in ("initial", "continued", "final") if s in c}, "transition measured profile census")
    for (name, stage), rows in groups.items():
        depths = [float(r["depth_mm"]) for r in rows]
        require(len(depths) > 1 and depths[0] == 0 and depths[-1] == 1 and all(b > a for a, b in zip(depths, depths[1:])), "transition incomplete profile")
        info = cases[name][stage]
        require(info["samples"] and len(info["onsets_0_1_V_cm"]) == 2 and len(info["target_spacings_um"]) == 2 and all(x > 0 for x in info["target_spacings_um"]), "transition missing profile measurements")
        for sample in info["samples"]:
            check_csv([next(r for r in rows if float(r["depth_mm"]) == sample["depth_mm"])], [sample])
        for threshold, recorded in zip((0, 1), info["onsets_0_1_V_cm"]):
            i = next((j for j, r in enumerate(rows) if float(r["E_V_cm"]) > threshold), None)
            require(recorded == (None if i is None else [None if i == 0 else depths[i-1], depths[i]]), "transition onset/profile mismatch")
    for c in cases.values():
        require(c["status"] in ("accepted_fixed_grid", "budget_failed", "failed"), "transition unfinished case")
        if c["status"] == "budget_failed":
            require(c["E_checks"] and c["W_checks"] and not (c["E_accepted"] and c["W_accepted"]), "transition missing budget failure")
        if c["status"] == "accepted_fixed_grid":
            require(any(n == c["case"] for n, _ in groups), "transition accepted without profile")
            for key, tol in (("E", 5e-6), ("W", 1e-8)):
                checks = c[key + "_checks"]
                require(c[key + "_accepted"] is True and len(checks) >= 2 and checks[-1]["consecutive_passes"] >= 2, "transition false case acceptance")
                require(all(0 <= d["frozen"]["max"] <= tol and 0 <= d["full_sweep"]["potential"] <= tol and (key == "W" or (0 <= d["poisson"]["max"] <= tol and 0 <= d["frozen"]["max_alpha_voltage"] <= tol and 0 <= d["full_sweep"]["alpha_voltage"] <= tol)) for d in checks[-2:]), "transition residual gate failed")
                require(checks[-1]["elapsed_seconds"] <= held["limits"]["seconds"] and ("initial" not in c or c[key + "_repaint"]["max_change"] <= tol), "transition time/repaint gate failed")
                require(c[key + "_final_repaint"]["max_change"] <= tol and all(d["nodes"] > 0 and d["max_error"] <= tol for d in c[key + "_geometric_contacts"]), "transition contact gate failed")
    expected = []
    references = {n + '_' + s: rows for (n, s), rows in groups.items()}
    references.update({n: rows for (n, s), rows in groups.items() if s == "final"})
    for c in g["comparisons"]:
        require(c["reference"] in references and c["candidate"] in references, "transition unknown comparison case")
        a, b = references[c["reference"]], references[c["candidate"]]
        require([r["depth_mm"] for r in a] == [r["depth_mm"] for r in b] and math.isclose(c["max_W"], max(abs(float(x["W"])-float(y["W"])) for x, y in zip(a, b)), rel_tol=1e-12, abs_tol=1e-15), "transition comparison/profile mismatch")
        expected.append(dict(reference=c["reference"], candidate=c["candidate"], normalized_E=c["normalized_E"], onset0_shift_mm=c["onset_shifts_mm"][0] if c["onset_shifts_mm"][0] is not None else "nothing", onset1_shift_mm=c["onset_shifts_mm"][1] if c["onset_shifts_mm"][1] is not None else "nothing", max_W=c["max_W"], passed=c["passed"]))
        if c["passed"]:
            require(0 <= c["normalized_E"] <= .01 and c["onset1_separation_upper_mm"] is not None and 0 <= c["onset1_separation_upper_mm"] <= .002 + 1e-14, "transition comparison gate failed")
    check_csv(comparisons, expected)
    if g["status"] == "bounded_numerical_convergence":
        require(g["nested_converged"] is True and g["baseline_accepted"] is True and all(n in cases and cases[n]["status"] == "accepted_fixed_grid" for n in ("min50", "min25", "nested0", "nested1", "nested2", "nested2_cold")), "transition false convergence")
        passed = {(c["reference"], c["candidate"]) for c in g["comparisons"] if c["passed"]}
        require({("nested0", "nested1"), ("nested1", "nested2"), ("nested2", "nested2_cold")} <= passed, "transition missing convergence comparisons")
        cold = next(c for c in g["comparisons"] if c["candidate"] == "nested2_cold")
        require(0 <= cold["max_V"] <= 5e-6 and 0 <= cold["max_W_grid"] <= 1e-8 and 0 <= cold["alpha_voltage_difference"] <= 5e-6, "transition cold/warm gate failed")


def load_transition(directory):
    directory = common.local_path(directory)
    report = common.relative_file(directory, "report.json").read_bytes()
    g = json.loads(report)
    finite_tree(g)
    raw = {public: common.relative_file(directory, original).read_bytes() for public, original in GRID_FILES.items()}
    g.update(report_sha256=hashlib.sha256(report).hexdigest(), reporter_test_sha256=common.sha256(Path(__file__).with_name("test_lithium_report.py")), profiles=csv_rows(raw["transition-profiles.csv"]),
             provenance_scope="Project and declared native identities checked; installed SDK not reopened. Native fixed-point checks are not independent PDE residual proof or physical CCE validation.")
    validate_transition(g, raw)
    require(common.sha256(directory / "report.json") == g["report_sha256"] and all(common.sha256(directory / n) == h for n, h in g["artifacts"].items()), "transition input changed")
    return compact_grid(g), raw


def axes_equal(actual, expected):
    if isinstance(expected, dict):
        require(isinstance(actual, dict), "axes comparison object")
        for k, v in expected.items(): axes_equal(actual[k], v)
    elif isinstance(expected, list):
        require(isinstance(actual, list) and len(actual) == len(expected), "axes comparison array")
        for a, b in zip(actual, expected): axes_equal(a, b)
    else:
        require(type(actual) is bool and actual is expected if isinstance(expected, bool) else
                isinstance(actual, (int, float)) and not isinstance(actual, bool) and math.isclose(actual, expected, rel_tol=1e-12, abs_tol=1e-14) if isinstance(expected, (int, float)) else actual == expected, "axes comparison mismatch")


def axes_comparison(a, b, reference=None):
    require([r["depth_mm"] for r in a] == [r["depth_mm"] for r in b], "axes profile support")
    onsets = lambda rows: [next(([None if j == 0 else rows[j-1]["depth_mm"], r["depth_mm"]] for j, r in enumerate(rows) if r["magnitude_V_cm"] > t), None) for t in (0, 1)]
    shifts = [None if x is None or y is None or None in x+y else [v-u for u, v in zip(x, y)] for x, y in zip(onsets(a), onsets(b))]
    x, y = onsets(a)[1], onsets(b)[1]
    upper = None if x is None or y is None or None in x+y else max(abs(x[0]-y[1]), abs(x[1]-y[0]))
    reference = b if reference is None else reference
    require([r["depth_mm"] for r in reference] == [r["depth_mm"] for r in b], "axes normalization support")
    norm = max(math.sqrt(sum((y[k]-x[k])**2 for k in ("Ex_V_cm", "Ey_V_cm", "Ez_V_cm"))) / max(1., r["magnitude_V_cm"]) for x, y, r in zip(a, b, reference))
    return dict(normalized_E=norm, onset_bracket_shifts_mm=shifts, onset1_separation_upper_mm=upper,
                max_local_source_difference_cm3=max(abs(y["alpha"]*y["netdensity_cm3"]-x["alpha"]*x["netdensity_cm3"]) for x, y in zip(a, b)), passed=norm <= .01 and upper is not None and upper <= .002+1e-14)


def validate_axes(g, raw):
    finite_tree(g); common.check_public(g)
    require(g["schema_version"] == 1 and g["kind"] == "AK02_transition_axes" and g["status"] in ("completed_attribution_diagnostics", "partial_cases"), "axes unfinished/invalid report")
    require(g["expected_case_count"] == 7 and g["final_sources_unchanged"] is True and 0 <= g["runtime_seconds"], "axes invalid source/runtime")
    held = dict(temperature_K=77, bias_V=500, threads=2, precision="Float64", sor=1, fresh_sweeps=40000, continuation_sweeps=20000, case_seconds=900, node_cap=250000, seed="none: deterministic")
    require(g["held_settings"] == held, "axes settings/budget changed")
    p = g["provenance"]; hash_map(ROOT / "simulation", p["sources"]); validate_transition_provenance(p["Tprovenance"])
    source = (ROOT / "simulation/diagnose_transition_axes.jl").read_text(encoding="utf-8").split("for (n,h)", 1)[0]
    helpers = dict(re.findall(r'"([^"\n]+)"\s*=>\s*"([0-9a-f]{64})"', source))
    require(set(helpers) == {"diagnose_transition_grid.jl", "test_transition_grid.jl"} and set(p["sources"]) == set(helpers) | {"diagnose_transition_axes.jl", "test_transition_axes.jl"}, "axes source inventory")
    require(all(p["sources"][n] == h == p["Tprovenance"]["sources"][n] for n, h in helpers.items()), "axes helper identity")
    require(g["reporter_test_sha256"] == common.sha256(Path(__file__).with_name("test_lithium_report.py")), "axes reporter tests changed")
    digest_map({"report.json": g["report_sha256"], **g["artifacts"]})
    require(set(g["artifacts"]) == set(AXES_FILES.values()), "axes artifact inventory")
    for public, original in AXES_FILES.items():
        require(hashlib.sha256(raw[public]).hexdigest() == g["artifacts"][original], "axes CSV hash mismatch")
        common.check_public(raw[public].decode("utf-8"))
    profiles, comparisons = [csv_rows(raw[n], n) for n in AXES_FILES]
    require(profiles == g["profiles"], "axes changed profiles")
    cases = {c["case"]: c for c in g["cases"]}; accepted = lambda n: cases[n]["status"] == "accepted_fixed_grid"
    require(len(cases) == len(g["cases"]) and set(cases) == set(AXES_CASES if g["baseline_accepted"] else AXES_CASES[:2]), "axes case census")
    require(type(g["baseline_accepted"]) is bool and g["baseline_accepted"] == all(accepted(n) for n in AXES_CASES[:2]), "axes baseline claim")
    require((g["status"] == "completed_attribution_diagnostics") == (len(cases) == 7 and all(accepted(n) for n in cases)), "axes completion claim")
    require(g["runtime_seconds"]+1e-9 >= sum(c["elapsed_seconds"] for c in cases.values()), "axes serial runtime mismatch")
    groups = {}
    for row in profiles:
        require(row["case"] in cases and row["stage"] in ("initial", "final"), "axes unknown profile")
        r = {k: float(v) for k, v in row.items() if k not in ("case", "stage")}
        require(all(math.isfinite(v) for v in r.values()) and r["magnitude_V_cm"] >= 0 and 0 <= r["alpha"] <= 1 and r["pointbits"] >= 0 and r["pointbits"].is_integer(), "axes invalid profile")
        axes_equal(r["magnitude_V_cm"], math.sqrt(sum(r[k]**2 for k in ("Ex_V_cm", "Ey_V_cm", "Ez_V_cm"))))
        groups.setdefault((row["case"], row["stage"]), []).append(r)
    require(set(groups) == {(n, s) for n, c in cases.items() for s in ("initial", "final") if s+"_profile" in c}, "axes profile census")
    for (name, stage), rows in groups.items():
        info = cases[name][stage+"_profile"]; ds = [r["depth_mm"] for r in rows]
        require(len(ds) == info["samples"] == 2001 and ds[0] == 0 and ds[-1] == 1 and all(math.isclose(d, j*.0005, rel_tol=0, abs_tol=1e-14) for j, d in enumerate(ds)) and all(y > x for x, y in zip(ds, ds[1:])), "axes incomplete profile")
        require(info["csv_stage"] == stage and len(info["target_spacings_um"]) == 2 and all(v > 0 for v in info["target_spacings_um"]), "axes actual spacing")
        grid = cases[name]["nativeitem"]["E_grid"]; compact_grid(grid)
        for axis, target, spacing in zip((0, 2), (.01215, .0047), info["target_spacings_um"]):
            ticks = grid["ticks_m_rad_m"][axis]; i = min(max(sum(t <= target for t in ticks)-1, 0), len(ticks)-2)
            axes_equal(spacing, (ticks[i+1]-ticks[i])*1e6)
        axes_equal(info["E0.5_V_cm"], rows[1000]["magnitude_V_cm"])
        axes_equal(info["onsets_0_1_V_cm"], [next(([None if j == 0 else ds[j-1], ds[j]] for j, r in enumerate(rows) if r["magnitude_V_cm"] > t), None) for t in (0, 1)])
    for name, c in cases.items():
        n = c["nativeitem"]; require(n["case"] == name and c["status"] in ("accepted_fixed_grid", "budget_failed") and c["elapsed_seconds"] >= 0, "axes invalid case")
        axes_equal(c["within_cooperative_time_budget"], c["elapsed_seconds"] <= held["case_seconds"])
        require(c["profile"] == c.get("final_profile", c.get("initial_profile")), "axes last profile mismatch")
        if "E_grid" in n:
            shape = n["E_grid"]["shape"]; require(len(shape) == 3 and shape[1] == 1 and all(type(x) is int and x > 0 for x in shape) and math.prod(shape) <= held["node_cap"], "axes actual dimensions/budget")
        if "final_profile" in c:
            require("E_grid" in n, "axes missing actual dimensions")
            require(type(n["E_accepted"]) is bool and accepted(name) == (n["E_accepted"] and bool(n["E_geometric_contacts"]) and all(d["nodes"] > 0 and 0 <= d["max_error"] <= 5e-6 for d in n["E_geometric_contacts"]) and c["within_cooperative_time_budget"]), "axes inconsistent acceptance/budget")
            digest_map(n["E_final_native_hashes"])
            require(set(n["E_final_native_hashes"]) == {"potential", "imp_scale", "point_types", "q_eff_imp", "q_eff_fix", "ϵ_r"}, "axes case source identity")
        if name not in AXES_CASES[:2] and "final_profile" in c:
            ident = c["initial_identity"]; require(c["rebuild_identity_verified"] is True and ident["grid"] == n["E_grid"], "axes initial identity")
            require(c["initial_potential_source"] == ("min25" if name == "g22_from25" else "min50"), "axes starting potential provenance")
            require(set(ident) == {"q_eff_imp", "q_eff_fix", "ϵ_r", "volume_weights", "sor_const", "point_types", "imp_scale", "grid", "axis_bytes", "geom_weights"} and len(ident["axis_bytes"]) == 3 and ident["geom_weights"], "axes coefficient inventory")
            require(c["independent_parent_storage_verified"] is True and c["parent_before"] == c["parent_after"] and c["parent_before"], "axes parent state changed")
            digest_map({k: ident[k] for k in ("q_eff_imp", "q_eff_fix", "ϵ_r", "volume_weights", "sor_const", "point_types", "imp_scale")})
            digest_map({str(j): h for j, h in enumerate(ident["axis_bytes"]+ident["geom_weights"])}); digest_map({"inputV": c["inputVhash"]})
        if accepted(name):
            checks = n["E_checks"]; contacts = n["E_geometric_contacts"]
            require(n["E_accepted"] is True and (name, "final") in groups and len(checks) >= 2 and checks[-1]["consecutive_passes"] >= 2 and checks[-2]["consecutive_passes"] >= 1, "axes false acceptance")
            require(contacts and all(d["nodes"] > 0 and 0 <= d["max_error"] <= 5e-6 for d in contacts) and 0 <= n["E_final_repaint"]["max_change"] <= 5e-6, "axes contact gate")
            require(name not in AXES_CASES[:2] or 0 <= n["E_repaint"]["max_change"] <= 5e-6, "axes baseline repaint")
            require(c["elapsed_seconds"] <= held["case_seconds"] and 0 <= checks[-2]["sweeps"] < checks[-1]["sweeps"] <= held["continuation_sweeps" if name in AXES_CASES[:2] else "fresh_sweeps"], "axes accepted budget")
            require(all(0 <= d["elapsed_seconds"] <= held["case_seconds"] and all(0 <= v <= 5e-6 for v in (d["frozen"]["max"], d["frozen"]["max_alpha_voltage"], d["poisson"]["max"], d["full_sweep"]["potential"], d["full_sweep"]["alpha_voltage"])) for d in checks[-2:]), "axes native gates")
    final = {n: rows for (n, s), rows in groups.items() if s == "final"}; expected = []
    require([(d["reference"], d["candidate"]) for d in g["comparisons"]] == [(a, b) for a, b in AXES_PAIRS if a in final and b in final and "g22_from50" in final], "axes comparison census")
    require([(d["reference"], d["candidate"]) for d in g["unavailable_comparisons"]] == [(a, b) for a, b in AXES_PAIRS if g["baseline_accepted"] and not {a, b, "g22_from50"} <= final.keys()], "axes unavailable comparison census")
    for d in g["comparisons"]:
        a, b = d["reference"], d["candidate"]; calc = axes_comparison(final[a], final[b], final["g22_from50"]); calc["accepted_inputs"] = accepted(a) and accepted(b) and accepted("g22_from50"); calc["passed"] &= calc["accepted_inputs"]
        calc.update(accepted_endpoints=accepted(a) and accepted(b), accepted_reference=accepted("g22_from50"))
        calc.update(normalization_reference="g22_from50: pointwise max(1 V/cm, norm(E22))", signed_radial_difference_V_cm=[y["Ex_V_cm"]-x["Ex_V_cm"] for x, y in zip(final[a], final[b])])
        axes_equal(d, calc); expected.append({k: "nothing" if d[k] is None else d[k] for k in HEADERS["axes-comparisons.csv"].split(',')})
    check_csv(comparisons, expected); same = g["same_grid"]
    if {"g22_from50", "g22_from25"} <= final.keys():
        a, b = "g22_from50", "g22_from25"; calc = axes_comparison(final[a], final[b]); axes_equal(same["profilecomparison"], calc)
        identical = cases[a]["initial_identity"] == cases[b]["initial_identity"]
        require(identical and cases[a]["nativeitem"]["E_grid"] == cases[b]["nativeitem"]["E_grid"], "axes same-grid coefficients differ")
        require(same["maxV"] >= 0 and same["alphavoltage"] >= 0 and same["maxinitVdifference"] >= 0, "axes same-grid values")
        require(max(abs(x["V"]-y["V"]) for x, y in zip(final[a], final[b])) <= same["maxV"]+1e-10, "axes full voltage/profile mismatch")
        require(0 <= same["alphavoltage_update_only"] <= same["alphavoltage"] and same["whole_grid_vector_difference_V_cm"] >= 0 and type(same["classification_changes"]) is int and same["classification_changes"] >= 0, "axes whole-grid diagnostics")
        axes_equal(same, dict(inconclusive=not (accepted(a) and accepted(b)), accepted_inputs=accepted(a) and accepted(b), coefficients_identical=identical, passed=accepted(a) and accepted(b) and identical and same["maxV"] <= 5e-6 and same["alphavoltage"] <= 5e-6 and calc["passed"]))
    else:
        axes_equal(same, dict(accepted_inputs=False, coefficients_identical=False, maxV=None, alphavoltage=None, profilecomparison=None, passed=False, inconclusive=True))
    if {"g11", "g12", "g21", "g22_from50"} <= final.keys():
        f = g["factorialsummary"]; four = [final[n] for n in ("g11", "g12", "g21", "g22_from50")]
        vectors = [[v[3][k]-v[2][k]-v[1][k]+v[0][k] for k in ("Ex_V_cm", "Ey_V_cm", "Ez_V_cm")] for v in zip(*four)]
        sources = [v[3]["alpha"]*v[3]["netdensity_cm3"]-v[2]["alpha"]*v[2]["netdensity_cm3"]-v[1]["alpha"]*v[1]["netdensity_cm3"]+v[0]["alpha"]*v[0]["netdensity_cm3"] for v in zip(*four)]
        axes_equal(f, dict(depth_mm=[r["depth_mm"] for r in four[0]], signed_radial_profile_V_cm=[v[0] for v in vectors], maxnorm_V_cm=max(math.sqrt(sum(x*x for x in v)) for v in vectors), normalized_interaction=max(math.sqrt(sum(x*x for x in v))/max(1., r["magnitude_V_cm"]) for v, r in zip(vectors, four[3])), normalization_reference="g22_from50: pointwise max(1 V/cm, norm(E22))", signed_local_source_interaction_cm3=sources, max_local_source_interaction_cm3=max(map(abs, sources)), accepted_inputs=all(accepted(n) for n in ("g11", "g12", "g21", "g22_from50")), initialization_test_passed=same["passed"]))
    else:
        require(g["factorialsummary"] is None, "axes incomplete factorial with success data")
    require(g["baseline_accepted"] or g["crosses_blocked_reason"], "axes missing blocked reason")


def load_axes(directory):
    directory = common.local_path(directory); report = common.relative_file(directory, "report.json").read_bytes(); g = json.loads(report)
    raw = {p: common.relative_file(directory, n).read_bytes() for p, n in AXES_FILES.items()}
    g.update(report_sha256=hashlib.sha256(report).hexdigest(), reporter_test_sha256=common.sha256(Path(__file__).with_name("test_lithium_report.py")), profiles=csv_rows(raw["axes-profiles.csv"]))
    validate_axes(g, raw); result = compact_grid(g)
    for c, original in zip(result["cases"], g["cases"]):
        if "E_grid" in original["nativeitem"]: c["nativeitem"]["E_grid"] = original["nativeitem"]["E_grid"]  # Small actual axes support portable spacing checks.
        if "initial_identity" in original: c["initial_identity"]["grid"] = original["initial_identity"]["grid"]
    validate_axes(result, raw)
    require(common.sha256(directory / "report.json") == g["report_sha256"] and all(common.sha256(directory / n) == h for n, h in g["artifacts"].items()), "axes input changed")
    return result, raw


def render_axes(g):
    out = '<section><h2>Initialization and radial/axial attribution</h2><p class="warning">' + escape(g["status"]) + ': E-only numerical check on the current radial line; not W, drift or CCE accuracy. Native acceptance is not convergence. Failed agreement or exhausted budgets do not establish nonuniqueness. Crossed effects remain conditional on initialization agreement.</p>'
    out += '<p>Physical Li-contact research concerns partial charge collection through diffusion, drift and recombination. This check asks whether the starting field or radial/axial mesh changes the computed electric field; these are not experimental curves. Profiles follow r = 12.65 - depth mm at phi = 0, z = 4.7 mm, over 0 to 1 mm depth. Source accounting counts grid nodes, not new gamma events. Prior nested grids remain unconverged and the earlier 15.1-percentage-point Li response warning remains unresolved.</p>'
    rows = []
    for c in g["cases"]:
        n, p = c["nativeitem"], c["profile"] or {}; last = (n.get("E_checks") or [{}])[-1]
        rows.append([display_number(v) for v in (c["case"], n.get("E_grid", {}).get("shape"), p.get("target_spacings_um"), (p.get("onsets_0_1_V_cm") or [None, None])[1], c["status"], last.get("sweeps"), c["elapsed_seconds"])])
    out += table(("Case", "Actual r/phi/z nodes", "Actual radial/axial spacing (um)", "E > 1 V/cm onset (mm)", "Native acceptance", "Sweeps", "Cooperative time budget (s / 900)"), rows)
    series = [(n, color, False, [(float(r["depth_mm"]), float(r["magnitude_V_cm"]), 0) for r in g["profiles"] if r["case"] == n and r["stage"] == "final"]) for n, color in zip(("g11", "g12", "g21", "g22_from50"), ("#006c91", "#ae3f15", "#596324", "#703da0"))]
    if all(s[3] for s in series): out += plot(series, "Electric field (V/cm), computed profiles")
    out += '<p>The local axial spacing at this sampled midheight remains 90.625 um in these cases. Axial changes refine regions near the ends/bore; smaller onset shifts do not establish general axial-resolution insensitivity. The coarse-r axial vector comparison also fails its profile gate.</p>'
    same = g["same_grid"]
    out += '<h3>Same-grid starting-state agreement</h3>' + table(("Accepted inputs", "Identical coefficients", "Full max V difference (V)", "Alpha voltage (V)", "Vector relative difference", "Onset separation (mm)", "Agreement"), [[display_number(v) for v in (same["accepted_inputs"], same["coefficients_identical"], same["maxV"], same["alphavoltage"], (same["profilecomparison"] or {}).get("normalized_E"), (same["profilecomparison"] or {}).get("onset1_separation_upper_mm"), same["passed"])]])
    if not same["passed"]:
        out += '<p class="warning"><b>The declared same-grid global agreement gate did not pass.</b> Small local profile differences do not clear the full-domain voltage criterion. Crossed effects remain conditional numerical diagnostics.</p>'
    location = same.get("difference_location")
    if location:
        out += '<p>Supplementary localization, without changing acceptance: maximum voltage difference at ' + escape(display_number(location["max_V_position_mm"])) + ' mm; inside semiconductor: ' + escape(str(location["max_V_inside_semiconductor"])) + '. Maximum over semiconductor-member nodes: ' + escape(display_number(location["semiconductor_member_max_V"])) + ' V. No exterior nodes were removed from the original gate.</p>'
    out += '<h3>Computed four effects and interaction</h3>' + table(("Reference", "Candidate", "Vector / common E22 norm (floor 1 V/cm)", "Onset separation (mm)", "Local source difference (cm^-3)", "Inputs accepted", "Profile gate"), [[display_number(d[k]) for k in HEADERS["axes-comparisons.csv"].split(',')] for d in g["comparisons"]])
    if g["unavailable_comparisons"]: out += table(("Reference", "Candidate", "Unavailable because"), [(d["reference"], d["candidate"], d["reason"]) for d in g["unavailable_comparisons"]])
    if g["factorialsummary"]:
        f = g["factorialsummary"]; out += table(("Interaction", "Max vector (V/cm)", "Vector / common E22 norm", "Max local source (cm^-3)"), [["E22 - E21 - E12 + E11", display_number(f["maxnorm_V_cm"]), display_number(f["normalized_interaction"]), display_number(f["max_local_source_interaction_cm3"])]])
    return out + '<p>All settings, source identities and checkpoint histories: <a download href="summary.json">summary.json</a>. Original report SHA-256: <small style="overflow-wrap:anywhere">' + escape(g["report_sha256"]) + '</small></p><p>' + ' · '.join(f'<a download href="{n}">{n}</a>' for n in AXES_FILES) + '</p></section>'


def display_number(value):
    """Readable display only; full precision remains in JSON and CSV artifacts."""
    if value is None:
        return "not measured"
    if isinstance(value, float):
        return format(value, ".6g")
    if isinstance(value, (list, tuple)):
        return "[" + ", ".join(display_number(v) for v in value) + "]"
    return str(value)


def render_transition(g):
    out = '<section><h2>Transition grid audit — native numerical checks</h2><p class="warning">' + escape(g["status"]) + ': field gates only. Selected underconverged profiles are not converged solutions. The legacy signal/grid warning remains unresolved; no experimental accuracy or CCE claim.</p>'
    out += '<p>' + escape(g["provenance_scope"]) + '</p>'
    out += '<p>Contact checks cover grid nodes belonging to each electrode, not arbitrary between-node surface probes. Native source totals include fixed/contact cells and are bookkeeping diagnostics, not an independently integrated active charge. Fresh cases permit 20,000 initialization plus 20,000 continuation sweeps; the reported actual count is authoritative.</p>'
    if not any(c["case"].startswith("nested") for c in g["cases"]):
        out += '<p>Nested results absent: ' + escape(g["status"]) + ' (baseline budget/defects or baseline-only phase).</p>'
    rows, series, notes, brief = [], [], [], []
    for c in g["cases"]:
        last_e = (c.get("E_checks") or [{}])[-1]
        last_w = (c.get("W_checks") or [{}])[-1]
        last_profile = next((c[k] for k in ("final", "continued", "initial") if k in c), {})
        brief.append((c["case"], c["status"], c.get("E_grid", {}).get("shape"), last_profile.get("target_spacings_um"), (last_profile.get("onsets_0_1_V_cm") or [None, None])[1], last_e.get("frozen", {}).get("max"), last_w.get("frozen", {}).get("max")))
        measured = next((c[s] for s in ("final", "continued", "initial") if s in c), {})
        for key in ("E", "W"):
            d = (c.get(key + "_checks") or [{}])[-1]
            rows.append((c["case"], c["status"], key, c.get(key + "_grid", {}).get("shape", "not measured"), measured.get("target_spacings_um"), d.get("frozen", {}).get("max"), d.get("full_sweep", {}).get("potential"), (d.get("poisson") or {}).get("max"), [d.get("frozen", {}).get("max_alpha_voltage"), d.get("full_sweep", {}).get("alpha_voltage")], measured.get("onsets_0_1_V_cm"), d.get("sweeps"), c.get(key + "_seconds"), c.get("failure")))
        for stage in ("initial", "continued", "final"):
            if stage not in c:
                continue
            info = c[stage]
            notes.append('<p>' + escape(f'{c["case"]}/{stage}: radial/axial spacing {display_number(info["target_spacings_um"])} µm; E=0/1 V/cm reporting brackets {display_number(info["onsets_0_1_V_cm"])} mm') + '</p>')
            points = [(float(r["depth_mm"]), float(r["E_V_cm"]), 0) for r in g["profiles"] if (r["case"], r["stage"]) == (c["case"], stage)]
            series.append((c["case"] + '/' + stage, ("#006c91", "#ae3f15", "#596324", "#703da0")[len(series) % 4], stage == "initial", points))
        pairs = [(a, b) for a, b in (("before_first_W", "after_first_W_init"), ("before_first_W", "after_initial_W_solve"), ("before_W_continuation" if "before_W_continuation" in c else "before_first_W", "after_W_continuation")) if a in c and b in c]
        if pairs and all(c[a] == c[b] and c[a] for a, b in pairs):
            notes.append('<p>' + escape(c["case"]) + ': W did not mutate E in the recorded state-equality checks.</p>')
    out += table(("Case", "Status", "Grid r/phi/z", "Radial/axial step (µm)", "E > 1 V/cm onset (mm)", "E defect (V)", "W defect"), [[display_number(v) for v in row] for row in brief])
    out += '<details><summary>All residuals, iterations, spacings and state checks</summary>' + "".join(notes)
    out += table(("Case", "Status", "Field", "Actual shape", "Last E radial/axial spacing µm", "Last frozen defect", "Sweep defect", "Poisson defect", "Alpha voltage, frozen/sweep (V)", "Last E onsets 0/1 V/cm (mm)", "Sweeps", "Seconds", "Failure"), [[display_number(v) for v in row] for row in rows])
    out += "</details>"
    out += plot(series, "Electric field (V/cm), computed profiles")
    out += table(("Reference", "Candidate", "Field vector / finer norm", "Onset shifts mm", "1 V/cm separation upper mm", "Max W", "Passed"), [(c["reference"], c["candidate"], c["normalized_E"], c["onset_shifts_mm"], c.get("onset1_separation_upper_mm"), c["max_W"], c["passed"]) for c in g["comparisons"]])
    return out + '<p>' + ' · '.join(f'<a download href="{n}">{n}</a>' for n in GRID_FILES) + '</p><details><summary>Settings and provenance (full checkpoint history in summary.json)</summary><pre>' + escape(json.dumps({"status": g["status"], "held_settings": g["held_settings"], "provenance": g["provenance"], "report_sha256": g["report_sha256"], "note": "All native checkpoint histories, cold/warm results and preserved budget failures are in the adjacent summary.json download; no numerical records were discarded."}, indent=2, sort_keys=True)) + '</pre></details></section>'


def render(data):
    phase = data["metadata"]["phase"]
    failed = sum(not c["passed"] for c in data["sensitivities"])
    body = f'<p>Phase: <b>{escape(phase)}</b>. ' + {"all": "Complete fixed diagnostic workload: 200 original primaries (100 per model), 63 diffusive clouds and 9 noDiff controls.", "audit": "Audit only: 200 original primaries (100 per model); no depth/sensitivity scan performed.", "depth": "Depth only: no original-event audit performed; the producer input identity refers to the separate source run."}[phase] + '</p>'
    body += f'<p class="warning"><b>Not converged; diagnostic only.</b> Sensitivity screens failed: {failed} / {len(data["sensitivities"])}. Passing screens do not certify convergence. These are not experimental CCE or recoverable-charge estimates. No large decay run was performed.</p>'
    body += '<p>77 K override; canonical AK02 +500 V / SAP22 +700 V. Native bulk 1 ms / inactive 1 μs lifetimes are uncalibrated. Diffusive clouds: diffusion=true, end_drift_when_no_field=false, self_repulsion=false. noDiff controls: diffusion=false, end_drift_when_no_field=true.</p>'
    grid_checks = [c for c in data.get("seed_equivalence", []) if c["kind"] == "grid" and c["signal"] == "original_stats"]
    if grid_checks:
        largest = max(grid_checks, key=lambda c: abs(c["mean_difference"]))
        body += f'<p class="warning"><b>Grid sensitivity remains unresolved:</b> at {largest["depth_mm"]:.2f} mm, min25 minus min50 changes the native mean signal by {largest["mean_difference"]:+.5f} ({100*abs(largest["mean_difference"]):.1f} percentage points). A loose statistical screen is not close-agreement evidence. See the separate post-run seed analysis below.</p>'
    body += '<section><h2>Li contact: approximation, physics and numerical verification</h2><p>Zero field does not imply zero collection: carriers may diffuse into a depleted region before being lost. A binary dead-layer approximation cannot represent all slow or partially collected pulses. See the <a href="https://arxiv.org/abs/1207.6716">2012 contact study</a>, <a href="https://arxiv.org/abs/2207.11902">2023 transport model</a> and <a href="https://doi.org/10.1140/epjc/s10052-026-15508-3">2026 SSD RCC implementation</a>. Available models do not automatically calibrate AK02. Current grid discrepancies are numerical questions under fixed physical inputs; device-specific lifetime and profile calibration is separate.</p></section>'
    if "axis_attribution" in data:
        body += render_axes(data["axis_attribution"])
    if "transition_grid" in data:
        body += render_transition(data["transition_grid"])
    series = []
    for key, color in (("original", "#006c91"), ("no_trapping", "#ae3f15")):
        series.append(("Native trapping" if key == "original" else "Same-path NoTrapping", color, False, [(r["depth_mm"], r[key]["mean"], r[key]["seed_sem"]) for r in data["seed_means"]]))
        series.append(("noDiff " + key, color, True, [(c["depth_mm"], c[key + "_stats"]["mean"], 0) for c in data["clouds"] if not c["diffusion"]]))
    baseline = next(i for i in data["cases"] if i["model"] == "AK02" and i["case"] == "baseline")
    field = [(float(r["depth_mm"]), float(r["E_V_cm"]), 0) for r in data["profiles"] if r["grid_case"] == "baseline"]
    field_series = [("Baseline field (min50)", "#006c91", False, field)]
    contrast_field = [(float(r["depth_mm"]), float(r["E_V_cm"]), 0) for r in data["profiles"] if r["grid_case"] == "contrast25"]
    if contrast_field:
        field_series.append(("Contrast field (min25)", "#ae3f15", True, contrast_field))
    scan_note = 'Baseline 2 ns / 5 μs, N=32 parcels per seed, Nseeds=3. Mean across seeds ± seed-to-seed SEM; numerical seed variation, not physical confidence. Dashed: noDiff controls. No fractions clipped.' if phase != 'audit' else 'Field profile only; no seeded depth clouds were run in this phase.'
    body += '<section><h2>AK02 radial depth</h2><p>' + scan_note + '</p><div class="plots">' + plot(series, "Final induced / deposited energy (fraction)") + plot(field_series, "Electric field (V/cm)", baseline["compensation_depth_mm"]) + '</div><p>The physical distinctions under study are neutral n-type Li, depleted n-type transition, and depleted p-type bulk. Reported labels combine net-doping sign with nearest-grid depletion/inactive bits; they can disagree with the interpolated field and do not prove a continuous physical boundary. Net-zero impurity is labelled compensated. Compensation is separate from a field threshold. No Z-axis orientation or cryostat/source placement is inferred.</p></section>'
    rows = []
    for i in data["cases"]:
        cs = [c for c in data["clouds"] if c["grid_case"] == i["case"] and i["model"] == "AK02"]
        rows.append((i["model"] + '/' + i["case"], i["min_grid_mm"], i["rechecks"], len(cs), ', '.join(map(str, sorted({c["dt_ns"] for c in cs}))), ', '.join(map(str, sorted({c["horizon_ns"] for c in cs}))), i["field_attempt_wall_seconds"], sum(c["runtime_s"] for c in cs)))
    body += '<section><h2>min25 / min50 and time controls — not convergence</h2>' + table(("Case", "Min grid (mm)", "Rechecks", "Clouds", "Δt (ns)", "Horizon (ns)", "Field wall time (s)", "Cloud wall total (s)"), rows)
    body += table(("Screen", "Passed", "Total"), [(k, sum(c["passed"] for c in data["sensitivities"] if c["kind"] == k), sum(c["kind"] == k for c in data["sensitivities"])) for k in ("grid", "time_step", "horizon")]) + '<p>Runtime includes compilation. min25 versus min50 uses the two contrast cases (8 rechecks); baseline has 4. Screens use parcel SEM, distinct from the seed SEM above.</p></section>'
    body += '<section><h2>Why contact missing ≠ signal loss</h2><p>Induced signal depends on weighting-potential change along the path. A missing geometric contact alone does not measure signal loss. Conditional remaining Ramo budget assumes static weighting, eventual hole W=1 / electron W=0, and no future loss. It is not a physical recovery bound. Flags overlap and must not be summed into a species population.</p>'
    rows = []
    for a in data["audit"]:
        for s in ("electron", "hole"):
            f = a["species_counts"][s]
            rows.append((a["model"], s, a["primary_count"], a["zero_deposit_primaries"], a["deposits"], f["geometric_contact"], a["zero_E_and_stationary_counts"][s], f["at_step_limit"], a["energy_weighted_conditional_fraction"], a["energy_weighted_absolute_component_fraction"]))
    body += table(("Model", "Species", "Primaries", "Zero primaries", "Deposits", "geometric_contact", "exactly_zero_E AND stationary", "at_step_limit", "Signed conditional remainder / Edep (event aggregate)", "Noncancelling remainder / Edep (event aggregate)"), rows) if rows else '<p>No endpoint audit in this phase.</p>'
    body += '</section><section><h2>Limits and reproducibility</h2><p>Variable-D closure, finite conductivity, geometry/diffusion boundaries, and grid/time convergence remain unresolved. SAP22 is a non-Li cross-check, not a matched experimental control.</p><ul>' + ''.join('<li>' + escape(x) + '</li>' for x in data["metadata"]["limitations"]) + '</ul><p>CSV rows reproduce the plots; summary.json retains every cloud scalar outcome and each seed mean.</p><p>' + ' · '.join(f'<a download href="{name}">{name}</a>' for name in ("summary.json", *FILES[1:])) + '</p><details><summary>Input identity, parameters and source/template hashes</summary><pre>' + escape(json.dumps(data["metadata"], indent=2, sort_keys=True)) + '</pre></details></section>'
    comparisons = data.get("seed_equivalence", [])
    if comparisons:
        rows = [(c["kind"], c["depth_mm"], c["signal"], f'{c["mean_difference"]:+.6f}',
                 f'[{c["approximate_t95"][0]:+.6f}, {c["approximate_t95"][1]:+.6f}]',
                 "Within 0.02 in this diagnostic" if c["inside_0p02"] else "NOT demonstrated") for c in comparisons]
        incomplete = sum(not c["inside_0p02"] for c in comparisons)
        supplement = '<section><h2>Additional paired-seed check: a passing loose screen is not convergence</h2>'
        supplement += f'<p class="warning">{incomplete} of {len(comparisons)} paired-seed comparisons do not demonstrate agreement within 0.02 absolute signal fraction. Do not interpret the original screen passes as campaign readiness.</p>'
        supplement += '<p>This is a separately added post-run diagnostic: mean difference ± the 95% Student-t interval from three matched seed means (2 degrees of freedom). It is exploratory, distribution-dependent numerical sampling uncertainty, not physical CCE uncertainty. The comparisons share seeds and these intervals do not provide simultaneous 95% coverage. Horizon variants compare ensembles, not extensions of identical trajectories. The original screening results above are preserved.</p>'
        transition = next((c for c in comparisons if c["kind"] == "grid" and c["depth_mm"] == .5 and c["signal"] == "original_stats"), None)
        if transition:
            supplement += f'<p><b>At 0.50 mm: min25 minus min50 native response = {transition["mean_difference"]:+.5f} absolute fraction.</b> These are grid settings, not uniform cell resolutions.</p>'
        supplement += table(("Change", "Depth mm", "Signal", "Mean difference", "Approximate seed interval", "0.02 criterion"), rows) + '</section>'
        body += supplement
    body += '<p><a href="../index.html">Back to the detector library</a></p>'
    return TEMPLATE.replace("__BODY__", body)


def validate_bundle(directory):
    """Validate the compact published bundle; no detector calculation is run."""
    directory = common.no_links(Path(directory).absolute())
    data = common.load_json(common.relative_file(directory, "summary.json"))
    extra = {**(GRID_FILES if "transition_grid" in data else {}), **(AXES_FILES if "axis_attribution" in data else {})}
    require(sorted(p.name for p in directory.iterdir()) == sorted(("lithium.html", "summary.json", *FILES[1:], *extra)), "unexpected Li bundle files")
    for name in ("lithium.html", "summary.json", *FILES[1:], *extra):
        common.relative_file(directory, name)
    if "transition_grid" in data:
        validate_transition(data["transition_grid"], {n: (directory / n).read_bytes() for n in GRID_FILES})
    if "axis_attribution" in data:
        validate_axes(data["axis_attribution"], {n: (directory / n).read_bytes() for n in AXES_FILES})
    finite_tree(data)
    metadata = data["metadata"]
    require(metadata["exporter_sha256"] == common.sha256(Path(__file__)), "Li report exporter changed")
    require(metadata["template_sha256"] == hashlib.sha256(TEMPLATE.encode()).hexdigest(), "Li report template changed")
    hash_map(ROOT / "simulation", metadata["source_hashes"])
    for name in FILES[1:]:
        require(common.sha256(directory / name) == metadata["input_files_sha256"][name], "Li CSV changed")
    require((directory / "summary.json").read_bytes() == common.public_json_text(data).encode(), "Li summary encoding changed")
    require((directory / "lithium.html").read_bytes() == render(data).encode(), "Li HTML differs from summary")
    common.check_public(data)
    return data


def export(directory, output, grid_input=None, axes_input=None):
    directory = common.local_path(directory)
    output = common.local_path(output, new=True)
    require(not output.is_relative_to(directory) and not directory.is_relative_to(output), "input/output roots must be separate")
    raw = {name: common.relative_file(directory, name).read_bytes() for name in FILES}
    report = common.load_json(directory / "report.json")
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    clouds = validate(report)
    data = summarize(report, clouds, {name: csv_rows(raw[name], name) for name in FILES[1:]}, hashes)
    extra = {}
    if grid_input is not None:
        grid_root = common.local_path(grid_input)
        require(not output.is_relative_to(grid_root) and not grid_root.is_relative_to(output), "grid input/output roots must be separate")
        data["transition_grid"], extra = load_transition(grid_root)
    if axes_input is not None:
        axes_root = common.local_path(axes_input)
        require(not output.is_relative_to(axes_root) and not axes_root.is_relative_to(output), "axes input/output roots must be separate")
        data["axis_attribution"], axes_raw = load_axes(axes_root)
        extra.update(axes_raw)
    finite_tree(data)
    common.check_public(data)
    for name in FILES[1:]:
        common.check_public(raw[name].decode("utf-8"))
    page, summary = render(data), common.public_json_text(data)
    require(all(common.sha256(directory / name) == digest for name, digest in hashes.items()), "input changed during export")
    if axes_input is not None:
        axes = data["axis_attribution"]
        require(common.sha256(axes_root / "report.json") == axes["report_sha256"] and all(common.sha256(axes_root / n) == h for n, h in axes["artifacts"].items()), "axes input changed during export")
    common.no_links(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in {"lithium.html": page.encode(), "summary.json": summary.encode(), **{n: raw[n] for n in FILES[1:]}, **extra}.items():
        with (output / name).open("xb") as stream:
            stream.write(value)
    validate_bundle(output)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--grid-input", help="Optional completed M2d diagnostic directory")
    parser.add_argument("--axes-input", help="Optional completed M2e E-only diagnostic directory")
    args = parser.parse_args()
    try:
        export(args.input, args.output, grid_input=args.grid_input, axes_input=args.axes_input)
    except (ValueError, KeyError, TypeError, OSError, StopIteration, IndexError) as error:
        parser.exit(1, f"Li report refused: {error}\n")
