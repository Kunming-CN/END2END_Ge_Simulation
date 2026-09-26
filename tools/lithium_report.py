"""Export completed diagnose_lithium.jl schema 1; no solver or raw cache access."""
import argparse
import csv
import hashlib
import html
import io
import json
import math
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
    require(sorted(p.name for p in directory.iterdir()) == sorted(("lithium.html", "summary.json", *FILES[1:])), "unexpected Li bundle files")
    for name in ("lithium.html", "summary.json", *FILES[1:]):
        common.relative_file(directory, name)
    data = common.load_json(directory / "summary.json")
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


def export(directory, output):
    directory = common.local_path(directory)
    output = common.local_path(output, new=True)
    require(not output.is_relative_to(directory) and not directory.is_relative_to(output), "input/output roots must be separate")
    raw = {name: common.relative_file(directory, name).read_bytes() for name in FILES}
    report = common.load_json(directory / "report.json")
    hashes = {name: hashlib.sha256(value).hexdigest() for name, value in raw.items()}
    clouds = validate(report)
    data = summarize(report, clouds, {name: csv_rows(raw[name], name) for name in FILES[1:]}, hashes)
    finite_tree(data)
    common.check_public(data)
    for name in FILES[1:]:
        common.check_public(raw[name].decode("utf-8"))
    page, summary = render(data), common.public_json_text(data)
    require(all(common.sha256(directory / name) == digest for name, digest in hashes.items()), "input changed during export")
    common.no_links(output)
    output.mkdir(parents=True, exist_ok=False)
    for name, value in {"lithium.html": page.encode(), "summary.json": summary.encode(), **{n: raw[n] for n in FILES[1:]}}.items():
        with (output / name).open("xb") as stream:
            stream.write(value)
    validate_bundle(output)
    return data


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        export(args.input, args.output)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.exit(1, f"Li report refused: {error}\n")
