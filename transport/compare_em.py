"""Bounded EM-constructor sensitivity at deposited-energy level, not detector calibration."""
import argparse
import json
import math
from pathlib import Path
import re
import sys
import h5py
import numpy as np
import scipy
from scipy.stats import fisher_exact
import handoff as h

BANNERS = {"Livermore": "Using Livermore/LowEnergy electromagnetic physics",
           "Penelope": "Using Penelope Physics", "Option4": "Using EmPhysics Option 4"}
ENERGIES_KEV = (59.5, 662.0)  # Deliberate rounded monoenergetic tests, not complete isotope decays.

def wilson(k, n, z=1.959963984540054):
    h.require(type(k) is int and type(n) is int and n > 0 and 0 <= k <= n, "bad binomial census")
    p = k / n
    den = 1 + z*z/n
    center = (p + z*z/(2*n))/den
    half = z*math.sqrt(p*(1-p)/n + z*z/(4*n*n))/den
    return [max(0.0, center-half), min(1.0, center+half)]


def difference_interval(k1, n1, k2, n2):
    """Newcombe independent-binomial interval from Wilson score limits (no continuity correction)."""
    p1, p2 = k1/n1, k2/n2
    a, b = wilson(k1, n1)
    c, d = wilson(k2, n2)
    diff = p1-p2
    return [max(-1., diff-math.sqrt((p1-a)**2+(d-p2)**2)),
            min(1., diff+math.sqrt((b-p1)**2+(p2-c)**2))]


def atomic_flags(text):
    keys = {"fluorescence": "Fluorescence enabled", "auger": "Auger electron cascade enabled",
            "pixe": "PIXE atomic de-excitation enabled", "ignore_cuts": "De-excitation module ignores cuts"}
    result = {}
    for key, label in keys.items():
        values = re.findall(re.escape(label) + r"\s+([01])(?:\s|$)", text)
        h.require(values and len(set(values)) == 1, "missing/ambiguous atomic flag: " + key)
        result[key] = bool(int(values[0]))
    return result

def holm_adjust(pvalues):
    h.require(all(math.isfinite(p) and 0 <= p <= 1 for p in pvalues), "invalid p value")
    order = sorted(range(len(pvalues)), key=lambda i: pvalues[i])
    adjusted = [0.] * len(pvalues)
    previous = 0.
    for rank, i in enumerate(order):
        previous = max(previous, min(1., (len(pvalues)-rank)*pvalues[i]))
        adjusted[i] = previous
    return adjusted

def data_packages():
    result = {}
    for path in sorted((Path(sys.prefix)/"conda-meta").glob("geant4*.json")):
        item = json.loads(path.read_text())
        result[item["name"]] = {"version": item["version"], "build": item["build"]}
    h.require(result, "Geant4/data package versions are missing")
    return result

def validate_source(raw, meta):
    radius = max(p[0] for p in meta["contour_rz_mm"])
    zs = [p[1] for p in meta["contour_rz_mm"]]
    expected = np.array([radius+10, 0, (min(zs)+max(zs))/2])/1000
    v = raw["vtx"]
    origin = np.column_stack([v[k][:] for k in ("xloc", "yloc", "zloc")])
    particles = raw["particles"]
    momentum = np.column_stack([particles[k][:] for k in ("px", "py", "pz")])
    expected_momentum = np.array([-meta["energy_keV"]/1000, 0, 0])
    h.require(np.allclose(origin, expected, rtol=0, atol=1e-12), "source origin disagrees with side-on setup")
    h.require(np.allclose(momentum, expected_momentum, rtol=0, atol=1e-12), "source direction/energy disagrees with -x gamma")
    h.require(np.all(v["time"][:] == 0), "unexpected source time")

def summarize(energy, incident):
    energy = np.asarray(energy, dtype=float)
    h.require(energy.ndim == 1 and len(energy) >= 2 and np.isfinite(energy).all(), "invalid event energies")
    h.require(np.all(energy >= 0) and np.all(energy <= incident + 1e-6), "invalid event energy ledger")
    n = len(energy)
    positive = energy > 0
    full = np.abs(energy-incident) <= 1e-6
    bins = np.arange(0, math.ceil(incident/0.5)*0.5 + 0.5 + 1e-9, 0.5)
    counts, edges = np.histogram(energy[positive], bins=bins)
    h.require(int(counts.sum()) + int((~positive).sum()) == n, "histogram lost events")
    m = {"primaries": n, "zero_deposit": int((~positive).sum()), "deposited_events": int(positive.sum()),
         "fully_contained_events": int(full.sum()), "fully_contained_fraction": float(full.mean()),
         "fully_contained_fraction_wilson95": wilson(int(full.sum()), n),
         "deposited_fraction": float(positive.mean()), "deposited_fraction_wilson95": wilson(int(positive.sum()), n),
         "mean_deposited_keV_per_primary": float(energy.mean()),
         "mean_deposited_standard_error_keV": float(energy.std(ddof=1)/math.sqrt(n)),
         "containment_tolerance_keV": 1e-6,
         "spectrum_note": "0.5 keV bins exclude zero deposits; zeros are separately retained. No Fano/noise/charge loss/electronics smearing."}
    return m, edges, counts

def event_energies(directory, meta, status):
    truth = directory / "truth.lh5"
    h.require(status["status"] == "complete" and h.sha256(truth) == status["source_lh5_sha256"], "raw status/hash mismatch")
    with h5py.File(truth, "r") as raw:
        validate_source(raw, meta)
        ids = raw[h.TABLE + "/evtid"][:]
        deposits = raw[h.TABLE + "/edep"][:]
        n = int(raw["number_of_simulated_events"][()])
        h.require(n == meta["primary_count"] and np.all((ids >= 0) & (ids < n)), "invalid event IDs")
        totals = np.bincount(ids.astype(np.int64), weights=deposits, minlength=n)
        h.require(math.isclose(math.fsum(totals), math.fsum(deposits), abs_tol=1e-8, rel_tol=1e-12), "energy sum changed")
    return totals

def run(output, events=5000):
    h.require(type(events) is int and 100 <= events <= 50000, "events must be 100..50000 per case")
    output = h.local_path(output)
    h.require(not output.exists(), "refuse existing comparison output")
    output.mkdir(parents=True, exist_ok=False)
    report = {"status": "running", "scope": "Bare AK02 EM physics-list sensitivity; no semiconductor response or model-accuracy ranking",
              "model_id": "AK02", "model_sha256": h.PINNED["AK02"],
              "source_code_sha256": {"compare_em.py": h.sha256(__file__), "handoff.py": h.sha256(h.__file__)},
              "events_per_case": events, "cases": [], "geant4_packages": data_packages(),
              "transport_lock_sha256": h.sha256(h.ROOT/"transport/pixi.lock"), "scipy_version": scipy.__version__, "statistics": "Distinct seeds. Wilson marginal95 intervals; differences at finite counts are not automatically physical discrepancies.",
              "limitations": ["Synthetic side-on monoenergetic source; not the owner's on-lid experimental geometry.",
                              "Rounded59.5/662keV examples; not isotope branching/coincidence/encapsulation.",
                              "Default constructor atomic settings are recorded, not fitted. Production cuts stay fixed; no step-size convergence claim.",
                              "Agreement does not prove accuracy; disagreement requires statistics, settings and experiment checks."]}
    try:
        for ei, incident in enumerate(ENERGIES_KEV):
            for mi, em in enumerate((*h.EM_OPTIONS, "Livermore")):
                seed = 926100 + 100*ei + mi
                name = f"{incident:g}keV-{em}" + ("-repeat" if mi==3 else "")
                print("RUN", name, "primaries", events, "seed", seed, flush=True)
                directory = h.prepare("AK02", output/name, events=events, seed=seed, energy=incident, em=em, audit_physics=True)
                meta = json.loads((directory/"prepared.json").read_text())
                item = {"name": name, "EM_constructor": em, "independent_seed_control": mi==3, "incident_keV": incident, "seed": seed, "status": "running",
                        "geometry_sha256": meta["files_sha256"]["geometry.gdml"],
                        "macro_sha256": meta["files_sha256"]["run.mac"], "physics": meta["physics"]}
                report["cases"].append(item)
                status = h.run(directory)
                text = (directory/"run.log").read_text(errors="replace")
                h.require(BANNERS[em] in text, "actual runtime EM constructor banner missing")
                audit = [line.strip() for line in text.splitlines() if re.search(r"fluorescence|auger|pixe|deexcitation|de-excitation", line, re.I)]
                flags = atomic_flags(text)
                for region, cut in (("default", 0.1), ("sensitive", 0.01)):
                    h.require(f"Setting user defined production cuts for {region} region to {cut:g} mm" in text, "effective cut banner missing")
                values = event_energies(directory, meta, status)
                stats, edges, counts = summarize(values, incident)
                with (directory/"event-energies.csv").open("x") as csv:
                    csv.write("event_id,total_deposited_keV\n")
                    for index, value in enumerate(values): csv.write(f"{index},{value:.17g}\n")
                with (directory/"spectrum.csv").open("x") as csv:
                    csv.write("low_keV,high_keV,count,binomial_standard_error_fraction,wilson95_low,wilson95_high\n")
                    for lo, hi, count in zip(edges[:-1], edges[1:], counts):
                        p = int(count)/events
                        low, high = wilson(int(count), events)
                        csv.write(f"{lo:.17g},{hi:.17g},{int(count)},{math.sqrt(p*(1-p)/events):.17g},{low:.17g},{high:.17g}\n")
                item.update(stats, status="complete", raw_sha256=status["source_lh5_sha256"],
                            runtime_versions=status["versions"], atomic_parameter_lines=audit, atomic_flags=flags,
                            spectrum_sha256=h.sha256(directory/"spectrum.csv"))
                print(em, incident, "full containment", item["fully_contained_fraction"], item["fully_contained_fraction_wilson95"], flush=True)
        h.require(len({c["geometry_sha256"] for c in report["cases"]}) == 1, "geometry changed across constructors")
        report["containment_comparisons"] = []
        for incident in ENERGIES_KEV:
            cases = [c for c in report["cases"] if c["incident_keV"] == incident]
            baseline = cases[0]
            for other in cases[1:]:
                delta = other["fully_contained_fraction"]-baseline["fully_contained_fraction"]
                interval = difference_interval(other["fully_contained_events"], events, baseline["fully_contained_events"], events)
                report["containment_comparisons"].append({"incident_keV": incident, "baseline": baseline["name"],
                    "other": other["name"], "difference": delta, "independent_newcombe95": interval,
                    "contains_zero": interval[0] <= 0 <= interval[1],
                    "caution": "Exploratory marginal95 intervals, no multiple-comparison correction, no equivalence or accuracy claim"})
        # Added after inspecting the initial marginal intervals: explicitly post-hoc.
        posthoc = []
        for comparison in report["containment_comparisons"]:
            first = next(c for c in report["cases"] if c["name"] == comparison["baseline"])
            other = next(c for c in report["cases"] if c["name"] == comparison["other"])
            a, b = first["fully_contained_events"], other["fully_contained_events"]
            p = float(fisher_exact([[a, events-a], [b, events-b]], alternative="two-sided").pvalue)
            posthoc.append({"baseline": first["name"], "other": other["name"], "fisher_two_sided_p": p})
        for row, adjusted in zip(posthoc, holm_adjust([r["fisher_two_sided_p"] for r in posthoc])):
            row["holm_adjusted_p"] = adjusted
        report["posthoc_containment_family"] = {"comparisons": posthoc,
            "note": "Post-hoc exploratory family of six comparisons, including both same-constructor controls. Holm FWER correction allows dependent shared-baseline comparisons; no equivalence or model-accuracy conclusion."}
        h.load_model("AK02")
        report["status"] = "completed_sensitivity_only"
    except Exception as error:
        report["status"] = "failed"; report["error"] = str(error)
        if report["cases"] and report["cases"][-1]["status"] == "running": report["cases"][-1]["status"] = "failed"
        raise
    finally:
        h.publish_json(output/"comparison.json", report)
    return report

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--events", type=int, default=5000)
    args = parser.parse_args()
    run(args.output, args.events)
