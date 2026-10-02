"""Frozen ring inputs and the owner-authorized GeRC02 Li50min effective model.

Only the single annealing-time token changes. No geometry, transport dead layer,
operating-temperature override or field-cache reuse is performed here.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = {
    "GeRC02": "7a655caeb660c07df8fcd9af51cc0998daea15f16e31f9c6afcacb89daf39218",
    "KMRC01_candidate": "d4258a3b9f9c041b4da1998ded6b373833169ddcc76079f0a588785efe68b6b6",
}
DELTA_FROM = b"lithium_annealing_time: 30minute"
DELTA_TO = b"lithium_annealing_time: 50minute"


def require(ok, message):
    if not ok:
        raise ValueError(message)


def digest(body):
    return hashlib.sha256(body).hexdigest()


def local(path):
    path = Path(os.path.abspath(path))
    base = ROOT / ".local"
    require(path != base and path.is_relative_to(base), "output must be below project .local")
    for item in (base, *path.parents, path):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "linked output refused")
    require(path.resolve() == path and path.resolve().is_relative_to(base.resolve()), "output escapes project .local")
    return path


def inputs(model):
    import yaml
    require(model in PINS, "unsupported ring model")
    catalog = json.loads((ROOT / "models/catalog.json").read_text(encoding="utf-8"))
    entries = [x for x in catalog["detectors"] if x["id"] == model]
    require(len(entries) == 1, "missing/duplicate ring catalog identity")
    entry = entries[0]
    source = ROOT / "models" / (model + ".yaml")
    body = source.read_bytes()
    require(entry["model"] == source.name and digest(body) == entry["model_sha256"] == PINS[model], "frozen ring model changed")
    dependencies = {}
    for ref in entry["dependencies"]:
        path = ROOT / "models" / ref
        require(path.resolve().is_relative_to((ROOT / "models").resolve()), "dependency escapes models")
        pins = [x["sha256"] for x in catalog["dependencies"] if x["path"] == ref]
        require(len(pins) == 1 and digest(path.read_bytes()) == pins[0], "ring dependency changed")
        dependencies["models/" + ref] = pins[0]
    original = yaml.safe_load(body)
    if model == "GeRC02":
        require(body.count(DELTA_FROM) == 1 and DELTA_TO not in body, "annealing-time delta is not unique")
        effective = body.replace(DELTA_FROM, DELTA_TO, 1)
        parsed = yaml.safe_load(effective)
        expected = yaml.safe_load(body)
        expected["detectors"][0]["semiconductor"]["impurity_density"]["lithium_annealing_time"] = "50minute"
        require(parsed == expected, "effective model changed beyond annealing time")
    else:
        effective, parsed = body, original
    require(parsed["name"] == model and parsed["units"] == {"length": "mm", "angle": "deg", "potential": "V", "temperature": "K"}, "ring identity/units changed")
    return original, parsed, effective, dependencies


def contract(model, effective_ref):
    original, parsed, body, dependencies = inputs(model)
    semi = parsed["detectors"][0]["semiconductor"]
    contacts = parsed["detectors"][0]["contacts"]
    require(semi["temperature"] == 78 and [(x["id"], x["potential"]) for x in contacts] == [(1, 0), (2, 240 if model == "GeRC02" else -370)], "ring operating inputs changed")
    return {"kind": "ring_effective_model_v1", "model_id": model,
            "variant_id": "GeRC02_Li50min" if model == "GeRC02" else "KMRC01_candidate",
            "qualification": "nominal engineering example; not calibrated Li CCE" if model == "GeRC02" else "candidate; ring-width match",
            "source_model_ref": "models/" + model + ".yaml", "source_model_sha256": PINS[model],
            "effective_model_ref": effective_ref, "effective_model_sha256": digest(body),
            "dependencies_sha256": dependencies,
            "model_delta": {"path": "detectors[0].semiconductor.impurity_density.lithium_annealing_time", "from": "30minute", "to": "50minute"} if model == "GeRC02" else None,
            "geometry_unchanged": original["detectors"][0]["semiconductor"]["geometry"] == semi["geometry"],
            "stored_temperature_K": 78, "runtime_temperature_K": 77,
            "runtime_temperature_policy": "explicit native-consumer override; YAML bytes retain 78 K",
            "annealing_temperature_K": 553.15 if model == "GeRC02" else None,
            "annealing_time_minutes": 50 if model == "GeRC02" else None,
            "readout_contact_id": 1, "contact_potentials_V": {str(x["id"]): x["potential"] for x in contacts},
            "cache_identity": "effective-model SHA256 plus runtime temperature/solver settings; never 30min-field reuse"}


def prepare(model, output):
    output = local(output)
    require(not output.exists(), "effective-model output exists; preserve prior evidence")
    _, _, body, _ = inputs(model)
    output.mkdir(parents=True)
    if model == "GeRC02":
        path = output / "GeRC02.yaml"
        with path.open("xb") as stream:
            stream.write(body)
        ref = path.relative_to(ROOT).as_posix()
    else:
        ref = "models/KMRC01_candidate.yaml"
    result = contract(model, ref)
    with (output / "model-contract.json").open("x", encoding="utf-8", newline="\n") as stream:
        stream.write(json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n")
    validate(result)
    return result


def validate(value):
    require(type(value) is dict and value.get("model_id") in PINS, "wrong model contract")
    ref = value["effective_model_ref"]
    require(type(ref) is str and "\\" not in ref and not Path(ref).is_absolute() and ".." not in Path(ref).parts, "invalid effective-model reference")
    path = ROOT / ref
    if value["model_id"] == "GeRC02":
        path = local(path)
    else:
        require(ref == "models/KMRC01_candidate.yaml", "KM effective model must be the unchanged original")
    require(value == contract(value["model_id"], ref), "effective model contract semantic mismatch")
    _, _, expected, _ = inputs(value["model_id"])
    require(path.read_bytes() == expected, "effective model bytes differ from the authorized one-token variant")
    return value


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("prepare")
    p.add_argument("--model", choices=PINS, required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("check")
    p.add_argument("--contract", required=True)
    args = parser.parse_args()
    value = prepare(args.model, args.output) if args.command == "prepare" else validate(json.loads(local(args.contract).read_text(encoding="utf-8")))
    print(json.dumps(value, indent=2, sort_keys=True, allow_nan=False))


if __name__ == "__main__":
    main()
