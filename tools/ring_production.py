"""Maintained production entry: verify a real terminal pilot, then launch 10K.

Keeps the original campaign and computational source pins unchanged. The frozen
ring_run production option is internal; use this entry for production admission.
This checks recorded execution provenance, not cryptographic attestation.
"""
import argparse
import json
import sys
from pathlib import Path
import ring_run as r


def science_artifacts(modeldir):
    for name in ("transport/prepare-receipt.json", "transport/run.json", "response/run.json"):
        record = r.read(modeldir / name)
        r.require(record.get("test_only") is not True, "Test-only records cannot authorize production")
    with (modeldir / "transport/truth.lh5").open("rb") as stream:
        r.require(stream.read(8) == b"\x89HDF\r\n\x1a\n", "Pilot radiation container is not HDF5")


def stages(c, modeldir, records):
    model = modeldir.name
    expected = [
        r.transport_command("prepare", "--model", model, "--output", r.ref(modeldir / "transport"),
                            "--exporter", r.EXPORTER, "--events", "500", "--seed", str(r.SEEDS[model])),
        r.transport_command("run", "--directory", r.ref(modeldir / "transport")),
        r.transport_command("extract", "--directory", r.ref(modeldir / "transport"), "--chunk-size", "100"),
        r.response_command(c, modeldir, "abort")]
    pids = set()
    for stage, record, argv in zip(("prepare", "transport", "extract", "response"), records, expected, strict=True):
        r.require(record.get("test_only") is not True and record["status"] == "complete"
                  and record["exit_code"] == 0 and record["command_argv"] == argv
                  and record["source_sha256"] == c["source_sha256"]
                  and record["name"] == "pilot500-" + model + "-" + stage
                  and type(record["child_pid"]) is int and record["child_pid"] > 0
                  and type(record["supervisor_pid"]) is int and record["supervisor_pid"] > 0,
                  "Pilot execution receipt mismatch: " + stage)
        pids.add(record["supervisor_pid"])
    r.require(len(pids) == 1, "Pilot stages do not share the recorded supervisor")
    return pids.pop()


def launcher_intent(c, directory, model, selection, launch):
    argv = [sys.executable, "-u", "-B", str(r.ROOT / "tools/ring_run.py"), "run",
            "--directory", str(directory), "--phase", "pilot", "--model", selection]
    r.require(selection in ("both", model) and launch["command_argv"] == argv
              and launch["output_root"] == r.ref(directory)
              and launch["source_sha256"] == c["source_sha256"], "Pilot launcher intent changed")


def verify(directory, model):
    directory = r.local(directory); c = r.config(directory)
    modeldir = directory / "pilot500" / model
    science_artifacts(modeldir)
    result = r.pilot_gate(modeldir, model)
    r.require(r.equal(r.read(modeldir / "VERIFIED.json"), result), "Pilot VERIFIED result changed")
    paths = [directory / "stages" / ("pilot500-" + model + "-" + s + ".json")
             for s in ("prepare", "transport", "extract", "response")]
    supervisor = stages(c, modeldir, [r.read(p) for p in paths])
    launchers = [p for p in directory.glob("pilot-*-launcher.json") if r.read(p)["pid"] == supervisor]
    r.require(len(launchers) == 1, "Actual pilot launcher missing or ambiguous")
    launcher = launchers[0]; launch = r.read(launcher)
    launcher_intent(c, directory, model, launcher.name.removeprefix("pilot-").removesuffix("-launcher.json"), launch)
    exited = launcher.with_name(launcher.name.replace("-launcher.json", "-supervisor-exit.json"))
    terminal = r.read(exited)
    r.require(launch["source_sha256"] == c["source_sha256"] and terminal["pid"] == supervisor
              and terminal["unresolved_child_intent"] is False, "Uncertain or changed pilot supervisor")
    paths.extend((launcher, exited, modeldir / "VERIFIED.json", directory / "config.json"))
    return {"kind": "actual_ring_pilot_admission_v1", "model": model, "result": result,
            "source_sha256": c["source_sha256"], "execution_receipt_sha256": {r.ref(p): r.sha(p) for p in paths},
            "gate_source_sha256": {"tools/" + n: r.sha(r.ROOT / "tools" / n)
                                   for n in ("ring_production.py", "test_ring_production.py")},
            "scope": "Actual recorded pilot admission; not experimental certification or attestation"}


def start(directory, model):
    directory = r.local(directory)
    r.require(not (directory / ".supervisor.lock").exists(), "Prior worker lock requires owned inspection")
    admission = verify(directory, model)
    r.atomic(directory / ("production-" + model + "-admission.json"), admission, fresh=True)
    return r.start(directory, phase="production", model=model)


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("command", choices=("verify", "start")); p.add_argument("--directory", required=True)
    p.add_argument("--model", choices=r.MODELS, required=True); a = p.parse_args()
    print(json.dumps(globals()[a.command](a.directory, a.model), indent=2, allow_nan=False))
