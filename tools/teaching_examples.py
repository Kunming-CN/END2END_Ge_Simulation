"""Curate exact completed cryostat Cs137 records; no simulation or analog replay.

The six examples explain different saved signals, not a statistical population.
assemble(site) writes the maintained teaching reader; validate(site) reconstructs
its exact payload from pinned public inputs. Earlier bare-gamma archives stay
outside this generator.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import math
from pathlib import Path
import re
import zipfile

from site_routes import page_navigation

ROOT = Path(__file__).resolve().parents[1]
PAGE = "spectra/pipeline.html"
DATA = "spectra/teaching-examples.json"
GENERATORS = ("tools/teaching_examples.py", "tools/teaching_examples.html",
              "tools/focused_plots.js", "tools/site_routes.py")
FOLDERS = {
    "AK02": "examples/cs137-10k/AK02/response",
    "SAP22": "examples/cs137-10k/SAP22/response",
    "GeRC02": "examples/cs137-10k-rings/GeRC02/response",
    "KMRC01_candidate": "examples/cs137-10k-rings/KMRC01_candidate/response",
}
# These reviewed, completed inputs are intentionally frozen. Changing a source
# and recalculating a manifest does not silently replace the teaching evidence.
SOURCE_SHA256 = {
    "examples/cs137-10k/AK02/response/run.json": "db63be7876161e78054a45e6b8ea94097ccd1ba3567a86445f2ca13cc95ddb79",
    "examples/cs137-10k/AK02/response/signals.csv": "487dad13e67bf35f7230923119c390c7aa1eae8fd0b35b00095b6db4146e9585",
    "examples/cs137-10k/AK02/response/ledgers.zip": "916d30452e1f601db5298fd3303b0346d779c2c70ec44d2d9d2ae4ee04cc164a",
    "examples/cs137-10k/SAP22/response/run.json": "d982d0768f286488cf81d77dfb9503285f0a7614c43c3bc4b382021d7a87943c",
    "examples/cs137-10k/SAP22/response/signals.csv": "b27030e3ab6630bc49ee58d134b3802f7145da15a56ebc41c24b6c3bcfd6db90",
    "examples/cs137-10k/SAP22/response/ledgers.zip": "c9934b56ab7b03cf4a23be702fd3a585dbe7e2d931a13b0d1f70747cfb98e011",
    "examples/cs137-10k-rings/GeRC02/response/run.json": "eece3cafd82cebfe2bf26a85e99dbacba365c4f6c7ab60f67e60da6cb756c2d2",
    "examples/cs137-10k-rings/GeRC02/response/signals.csv": "21e49040cd0fe247d556980be963d913e2421de34f958938a99be168cd4e48a8",
    "examples/cs137-10k-rings/GeRC02/response/ledgers.zip": "849f64002f3826f8c24f00558226026e8c72ffc03b7f17c61935b0fe56d4f57d",
    "examples/cs137-10k-rings/KMRC01_candidate/response/run.json": "17e539fc64b905a9640b45d4f95acd1f74de3d3640ef99ba385fabd2568f4640",
    "examples/cs137-10k-rings/KMRC01_candidate/response/signals.csv": "dc53d63f4d3ad63f9da534bec0e1061dcf78e53c331aed5505b49afd4cb9a2de",
    "examples/cs137-10k-rings/KMRC01_candidate/response/ledgers.zip": "c97f23df5cd920725204a420bd30fa43561d5c27b1c3627adda83d67834714a8",
}
SELECTION = (
    ("GeRC02", 61, 0, "Near the 661.657 keV line",
     "661.6572831606164 keV deposited in this group. The native cap flags still apply; a close energy match does not establish Li collection accuracy."),
    ("SAP22", 155, 0, "A low-energy photon",
     "The recorded source photon is 32.2053811750089 keV. This is a low-energy example, not partial absorption of a 662 keV photon."),
    ("SAP22", 74, 0, "Partial energy deposition",
     "The recorded 661.6572831606165 keV decay photon leaves 403.12803770450375 keV in this group."),
    ("GeRC02", 69, 0, "Deposits at many positions",
     "25 positive-energy semiconductor deposits contribute to one pulse group. The signal is their grouped signed induction."),
    ("AK02", 213, 0, "Step-limit endpoints remain",
     "26 of 320 carrier parcels reach the numerical step limit. The accepted ADC result does not remove this native transport limitation."),
    ("KMRC01_candidate", 26, 0, "Negative native charge and fixed wiring",
     "Original native charge stays negative. The saved electronics derivative uses one fixed -1 wiring factor and an independent negative-charge injection calibration."),
)
ELECTRON_C = 1.602176634e-19
PRIVATE = re.compile(rb"[A-Za-z]:[\\/]+Users[\\/]|file:///|/home/[^/\s]+/|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}")


def require(ok, message):
    if not ok:
        raise ValueError(message)


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


LOADED_GENERATORS = {path: sha(ROOT / path) for path in GENERATORS}


def require_frozen_sources():
    require(LOADED_GENERATORS == {path: sha(ROOT / path) for path in GENERATORS},
            "Teaching sources changed after import; restart after writer freeze")


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=True,
                      separators=(",", ":"), allow_nan=False) + "\n"


def read_json(data):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            require(key not in result, "Duplicate saved JSON key: " + key)
            result[key] = value
        return result
    return json.loads(data, object_pairs_hook=unique,
                      parse_constant=lambda value: require(False, "Nonfinite saved JSON: " + value))


def available(site):
    """Only input availability; a changed or partial generated bundle still fails."""
    site = Path(site)
    return all((site / path).is_file() and not (site / path).is_symlink()
               for path in SOURCE_SHA256)


def current_from_charge(times, charge, eion, dt, end, wiring=1.0):
    """Mirror the original readout-bin operation order, including initial zero."""
    require(len(times) == len(charge) and len(times) >= 2 and
            times[0] == 0 and charge[0] == 0, "Complete charge starting at zero required")
    require(all(math.isfinite(v) for v in (eion, dt, end, wiring)) and
            eion > 0 and dt > 0, "Invalid recorded current parameters")
    tolerance = max(1e-9, dt * 1e-8)
    require(all(math.isfinite(t) and math.isfinite(q) and abs(t - i * dt) <= tolerance
                for i, (t, q) in enumerate(zip(times, charge))), "Charge original grid changed")
    steps = round(end / dt)
    require(end >= dt and abs(end - steps * dt) <= tolerance and steps < 500000,
            "Readout boundary is not on the original grid")
    factor = 1000 / eion * ELECTRON_C
    return [0.0 if i == 0 or i >= len(charge) else
            ((charge[i] * wiring) - (charge[i-1] * wiring)) * factor / dt * 1e18
            for i in range(steps + 1)]


def member_binding(report, name):
    binding = report.get("source_public_bindings", {}).get(name)
    return binding["public"]["sha256"] if binding else report["artifacts"][name]


def saved_members(archive, report, event_ids):
    """Stream each ledger once, retaining complete original selected records."""
    records, bindings = {}, {}
    for name in ("scalars.jsonl", "traces.jsonl", "truth.jsonl"):
        digest = hashlib.sha256()
        selected = []
        with archive.open(name) as stream:
            for line in stream:
                digest.update(line)
                value = read_json(line)
                if value.get("event_id") in event_ids:
                    selected.append(value)
        require(digest.hexdigest() == member_binding(report, name),
                "Saved archive member binding changed: " + name)
        records[name] = selected
        bindings[name] = digest.hexdigest()
    config_bytes = archive.read("readout-config.json")
    digest = hashlib.sha256(config_bytes).hexdigest()
    require(digest == member_binding(report, "readout-config.json"),
            "Saved readout configuration binding changed")
    bindings["readout-config.json"] = digest
    return records, read_json(config_bytes), bindings


def saved_charge(path, selected):
    result = {key: {"time_since_origin_ns": [], "induced_equivalent_energy_keV": []}
              for key in selected}
    with Path(path).open(encoding="utf-8", newline="") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ["event_id", "global_decay_id", "group_id",
                                      "time_since_origin_ns", "induced_equivalent_energy_keV"],
                "Saved signal CSV schema changed")
        for row in reader:
            key = (int(row["event_id"]), int(row["group_id"]))
            if key not in result:
                continue
            require(row["event_id"] == row["global_decay_id"], "Signal identity mismatch")
            result[key]["time_since_origin_ns"].append(float(row["time_since_origin_ns"]))
            result[key]["induced_equivalent_energy_keV"].append(float(row["induced_equivalent_energy_keV"]))
    return result


def exactly_one(rows, predicate, message):
    selected = [row for row in rows if predicate(row)]
    require(len(selected) == 1, message)
    return selected[0]


def build_payload(site):
    site = Path(site)
    require_frozen_sources()
    require(available(site), "Completed four-case teaching sources are incomplete")
    for path, expected in SOURCE_SHA256.items():
        require(sha(site / path) == expected, "Pinned teaching source changed: " + path)
    models, cases, source_members = {}, {}, {}
    for model, folder in FOLDERS.items():
        report = read_json((site / folder / "run.json").read_bytes())
        selections = [row for row in SELECTION if row[0] == model]
        keys = {(row[1], row[2]) for row in selections}
        with zipfile.ZipFile(site / folder / "ledgers.zip") as archive:
            records, config, bindings = saved_members(archive, report, {key[0] for key in keys})
            native = report.get("current", report)
            if model == "KMRC01_candidate":
                original_bytes = archive.read("original-native/run.json")
                native = read_json(original_bytes)["source"]
                bindings["original-native/run.json"] = hashlib.sha256(original_bytes).hexdigest()
        calibration = report.get("calibration", native["calibration"])
        wiring = report.get("readout_wiring", {"factor": 1.0})
        settings = {key: native[key] for key in (
            "bias_V", "temperature_K", "stored_temperature_K", "readout_contact_id",
            "nominal_drift_cap_ns", "parcels", "seed_family", "seed_rule", "diffusion",
            "end_drift_when_no_field", "self_repulsion", "drift_dt_ns",
            "ionisation_energy_eV", "grouping_policy", "environment", "source_sha256",
            "model_sha256")}
        models[model] = {
            "settings": settings, "calibration": calibration, "readout_config": config,
            "model_contract": report.get("model_contract"),
            "wiring": wiring, "counts": report.get("current_counts", native["counts"]),
            "native_status": native["status"],
            "current_status": report.get("current", native)["status"],
            "limitations": report.get("limitations", native["limitations"]),
            "source_folder": folder,
        }
        source_members[folder + "/ledgers.zip"] = bindings
        charges = saved_charge(site / folder / "signals.csv", keys)
        require(sha(site / folder / "signals.csv") == member_binding(report, "signals.csv"),
                "Saved charge CSV report binding changed")
        for _, event_id, group_id, title, explanation in selections:
            pulse = exactly_one(records["scalars.jsonl"],
                lambda row: row.get("event_id") == event_id and row.get("group_id") == group_id
                and row.get("record_kind") == "pulse", "Selected pulse missing or duplicated")
            decay = exactly_one(records["scalars.jsonl"],
                lambda row: row.get("event_id") == event_id and row.get("record_kind") == "decay",
                "Selected decay missing or duplicated")
            trace = exactly_one(records["traces.jsonl"],
                lambda row: row.get("event_id") == event_id and row.get("group_id") == group_id,
                "Selected trace missing or duplicated")
            truth = exactly_one(records["truth.jsonl"],
                lambda row: row.get("event_id") == event_id, "Selected truth missing or duplicated")
            charge = charges[(event_id, group_id)]
            require(pulse["trace_saved"] and pulse["deposited_energy_keV"] > 0,
                    "Selected example is not a saved nonzero pulse")
            require(pulse["global_decay_id"] == trace["global_decay_id"] == event_id and
                    pulse["origin_time_ns"] == trace["origin_time_ns"] == pulse["group"]["origin_time_ns"],
                    "Selected group identity or time origin changed")
            times, q = charge["time_since_origin_ns"], charge["induced_equivalent_energy_keV"]
            require(times[-1] == pulse["charge_end_ns"] and q[-1] == pulse["final_induced_keV"],
                    "Full native charge endpoint differs from scalar")
            analog = trace["trace"]
            require(all(len(analog[key]) == len(analog["time_ns"]) for key in (
                "current_bin_start_ns", "current_bin_end_ns", "current_nA",
                "induced_charge_fC", "preamp_V", "shaped_V")), "Sparse analog lengths differ")
            readout = pulse["readout"]
            currents = current_from_charge(times, q, calibration["ionisation_energy_eV"],
                                           calibration["time_step_ns"], readout["readout_end_ns"],
                                           wiring["factor"])
            require(analog["time_ns"][-1] <= readout["readout_end_ns"] and
                    all(0 <= t <= readout["readout_end_ns"] for t in analog["time_ns"]),
                    "Sparse analog sample outside original boundary")
            for i, t in enumerate(analog["time_ns"]):
                index = round(t / calibration["time_step_ns"])
                require(math.isclose(analog["current_nA"][i], currents[index], rel_tol=2e-13, abs_tol=1e-10),
                        "Saved electronics current differs from original full charge bin")
            positive_steps = [row for row in truth["steps"] if row["energy_keV"] > 0]
            cases[(model, event_id, group_id)] = {
                "model": model, "event_id": event_id, "group_id": group_id,
                "title": title, "explanation": explanation,
                "positive_deposit_count": len(positive_steps),
                "decay": decay, "pulse": pulse, "truth": truth,
                "saved_trace": trace, "native_charge": charge,
            }
    require(cases[("GeRC02", 69, 0)]["positive_deposit_count"] == 25,
            "Multi-position example deposit count changed")
    payload = {
        "kind": "curated_saved_cs137_teaching_v1",
        "selection_policy": "six explicit nonzero pulse groups from original first-four saved trace cohorts",
        "scope": "Curated signal examples, not a spectrum, random sample or measured detector prediction.",
        "time_origin": "Time since the selected pulse-group origin_time_ns; deposition delays are distinct from carrier drift.",
        "units": {"native_charge": "signed induced-equivalent keV", "display_charge": "fC",
                  "current": "nA at electronics input after fixed wiring",
                  "analog": "V", "time": "ns", "energy": "keV"},
        "models": models,
        "cases": [cases[(m, e, g)] for m, e, g, _, _ in SELECTION],
        "provenance": {
            "source_files_sha256": dict(SOURCE_SHA256), "archive_members_sha256": source_members,
            "generator_sha256": {path: sha(ROOT / path) for path in GENERATORS},
            "encoding": "json-compact-sorted-ascii-v1",
            "analog_policy": "Exact retained original analog samples only; no replay, interpolation data or invented early points.",
            "current_policy": "Exact original 2 ns bins from full saved native charge after the recorded fixed wiring, bounded by recorded readout_end_ns.",
        },
    }
    require_frozen_sources()
    require(not PRIVATE.search(canonical(payload).encode()), "Private metadata in teaching data")
    return payload


def render(payload):
    template = (ROOT / "tools/teaching_examples.html").read_text(encoding="utf-8")
    require(template.count("__TEACHING_DATA_JSON__") == template.count("__FOCUSED_PLOTS_JS__") ==
            template.count("__PAGE_NAVIGATION__") == 1, "Teaching template tokens changed")
    data = canonical(payload).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    return template.replace("__TEACHING_DATA_JSON__", data).replace(
        "__FOCUSED_PLOTS_JS__", (ROOT / "tools/focused_plots.js").read_text(encoding="utf-8")).replace(
        "__PAGE_NAVIGATION__", page_navigation(PAGE, dataset="teaching"))


def metadata(payload, html):
    data = canonical(payload).encode()
    return {"kind": payload["kind"], "selection": [[m, e, g] for m, e, g, _, _ in SELECTION],
            "sources": payload["provenance"]["source_files_sha256"],
            "generators": payload["provenance"]["generator_sha256"],
            "files": {DATA: {"sha256": hashlib.sha256(data).hexdigest(), "bytes": len(data)},
                      PAGE: {"sha256": hashlib.sha256(html.encode()).hexdigest(), "bytes": len(html.encode())}}}


def write_if_changed(path, data):
    path = Path(path)
    if not path.exists() or path.read_bytes() != data:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)


def assemble(site):
    site = Path(site)
    payload = build_payload(site)
    html = render(payload)
    write_if_changed(site / DATA, canonical(payload).encode())
    write_if_changed(site / PAGE, html.encode())
    return metadata(payload, html)


def validate(site):
    site = Path(site)
    require((site / DATA).is_file() and (site / PAGE).is_file(), "Partial teaching output")
    require(not (site / DATA).is_symlink() and not (site / PAGE).is_symlink(), "Linked teaching output")
    payload = build_payload(site)
    html = render(payload)
    require((site / DATA).read_bytes() == canonical(payload).encode(), "Teaching samples or source bindings changed")
    require((site / PAGE).read_bytes() == html.encode(), "Teaching rendering changed")
    return metadata(payload, html)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", type=Path)
    parser.add_argument("--validate", action="store_true")
    args = parser.parse_args()
    print(json.dumps((validate if args.validate else assemble)(args.site), indent=2))
