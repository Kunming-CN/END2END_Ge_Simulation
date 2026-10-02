"""Publish completed ring 10K saved data; never rerun radiation, SSD or electronics.

The explicit scene command uses the additive native Geant4 geometry inspector.
Build, validate and assemble consume completed saved artifacts only. Unknown
native quantities and original signed signals remain unchanged.
"""
from __future__ import annotations

from collections import Counter
import argparse
import csv
import gzip
import hashlib
import html
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import struct
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / ".local/ring-publication-v1"
CAMPAIGN = ROOT / ".local/ring-cs137-v1"
MODELS = ("GeRC02", "KMRC01_candidate")
PRIMARY_COUNT = 10000
SOURCES = ("tools/ring_publication.py", "tools/test_ring_publication.py", "tools/ring_scene.cc",
           "tools/geometry_events.py", "tools/hit_event_view.py", "tools/ring_run.py",
           "tools/ring_production.py", "tools/km_ring_run.py", "tools/ring_model_contract.py",
           "transport/cs137.py", "transport/handoff.py", "tools/geant4_scene/scene.cc",
           "tools/ring_saved_basis.py", "tools/test_ring_saved_basis.py")
WRITER = WORK / "build/WRITER-FROZEN-v1.json"
FROZEN = WORK / "build/SOURCE-FREEZE.json"
NATIVE_EXECUTABLE = WORK / "build/ring_scene"
METADATA = frozenset(("run.json", "ring-response.json", "input-contract.json", "input-prepared.json"))
LEDGER_NAMES = frozenset(("endpoints.csv", "endpoints.jsonl", "histograms.csv", "histograms.json",
    "input-contract.json", "input-prepared.json", "profile-input.json", "profile.json", "readout-config.json",
    "scalars.csv", "scalars.jsonl", "signals.csv", "summary.html", "traces.jsonl", "truth.csv", "truth.jsonl"))
SCALAR_COLUMNS = ("record_kind", "event_id", "global_decay_id", "group_id", "origin_time_ns",
                  "deposited_energy_keV", "final_induced_keV", "accepted", "rejection_reason", "record_json")
OMISSIONS = [
    "World-air steps are unscored. No connectors are invented across unrecorded paths.",
    "Track rows are creation vertices/momenta/identities, not continuous trajectories.",
    "STEP pre/post pairs are recorded chords, not curved microscopic paths or SSD drift.",
    "Native endpoint limits and failures remain explicit; no calibrated Li CCE or physical resolution claim.",
    "Analog samples are numerical samples; the digital output is a peak ADC code, not waveform acquisition.",
    "Nominal engineering mounting/source, not a surveyed replica; no measured waveform comparison.",
    "Curved-surface tessellation is visualization only; GDML is the exact geometry download.",
    "Parent solids include daughter regions; transparent surfaces are not a material occupancy map.",
    "Raw LH5, field caches, private paths and upstream .tg files stay local.",
]
PRIVATE = re.compile(
    rb"[A-Za-z]:[\\/]+Users[\\/]|/mnt/[a-z]/Users/|file:///|/home/[^/\s]+/|\.local[\\/]",
    re.I,
)
SECRET = re.compile(
    rb"BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY|gh[pousr]_[A-Za-z0-9]{25,}|sk-proj-[A-Za-z0-9_-]{25,}"
)
STAGES = (
    "deposited_per_decay", "deposited_per_group", "native_terminal_charge",
    "window_charge", "preamp_charge_equivalent", "analog_shaped_equivalent",
    "accepted_peak_ADC",
)
# Both existing mesh receipts were checked before this data-reader adaptation.
# Their exact native source/executable/GDML/scene bindings are still checked below.
PREVIOUS_SCENE_FREEZE = 'bb0464a99b1313b9d99d61dedde0ccb37d41b7371897e10389bf0f3dea8d8e7d'
PREVIOUS_RAW_FREEZE = '5d8fcd196125e3cc573ab4694c69de13824c60fdb6f33bf2ce0e6d2626e8bfa4'
PREVIOUS_RAW_RECEIPTS = {
    'GeRC02': '123e3d885a2f3a3b346d49173f09f21424e92bdce9744feff1ad0ce19f5268b0',
    'KMRC01_candidate': 'ca1f80fed59f6e6e753cbac8e9dd4eea68e75b0359b9523b2700180f17377898',
}
# This exact fully checked, completed export is the input to a saved-only web
# package. Historical acceptance is bound to its whole manifest, never to a
# caller-provided inventory or resealed source map.
FULL_BUNDLE_MANIFEST = 'e9ff0c6c1272d258dcfdd109055b8642587caf3ad1cde5fed2cb3334a03503d6'
DIRECT_RESPONSE = frozenset(('scalars.jsonl', 'histograms.json', 'signals.csv',
    'readout-input.csv', 'summary.html', 'run.json', 'ledgers.zip',
    'original-native/run.json', 'original-native/signals.csv',
    'original-native/scalars.jsonl', 'original-native/summary.html'))
MAX_WEB_FILE_BYTES = 95 * 1024 * 1024
MAX_SITE_BYTES = 1_000_000_000
EXISTING_SITE_BYTES = 767_604_359


def require(ok, message):
    if not ok:
        raise ValueError(message)


def finite(value):
    if isinstance(value, float):
        require(math.isfinite(value), "Nonfinite scientific scalar")
    elif isinstance(value, dict):
        for child in value.values():
            finite(child)
    elif isinstance(value, (list, tuple)):
        for child in value:
            finite(child)


def encoded(value):
    """Binary64 round-trippable JSON; negative zero is retained as -0.0."""
    finite(value)
    return (json.dumps(value, ensure_ascii=True, allow_nan=False,
                       separators=(",", ":")) + "\n").encode("utf-8")


def read(path):
    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)
    return json.loads(Path(path).read_text(encoding="utf-8-sig"), parse_constant=invalid,
                      parse_int=lambda value: -0.0 if value == "-0" else int(value))


def digest(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def exact(a, b):
    """Compare every scalar including type and IEEE-754 signed zero."""
    if type(a) is not type(b):
        return False
    if type(a) is float:
        return struct.pack(">d", a) == struct.pack(">d", b)
    if type(a) is dict:
        return a.keys() == b.keys() and all(exact(a[key], b[key]) for key in a)
    if type(a) in (list, tuple):
        return len(a) == len(b) and all(exact(x, y) for x, y in zip(a, b, strict=True))
    return a == b


def public_safe(body, label):
    require(not PRIVATE.search(body) and not SECRET.search(body), "Private metadata: " + label)
    body.decode("utf-8-sig")
    return body


def sanitized_metadata(value):
    """Explicit metadata derivative; NEVER apply this to scientific ledgers.

    Original and public bytes require separate bindings. Redaction records keep
    source-value hashes, without publishing the removed classified path. Numeric
    scalars are preserved exactly, including negative zero.
    """
    redactions = []

    def replacement(text, pointer, key=False):
        body = text.encode("utf-8")
        require(not SECRET.search(body), "Credential-shaped metadata must be reviewed")
        if not PRIVATE.search(body):
            return text
        h = hashlib.sha256(body).hexdigest()
        public = "classified-input-" + h if key else "[classified local path omitted]"
        redactions.append({"field_sha256": hashlib.sha256(pointer.encode()).hexdigest(),
                           "source_value_sha256": h, "public_value": public})
        return public

    def visit(item, pointer):
        if isinstance(item, dict):
            result = {}
            for name, child in item.items():
                require(type(name) is str, "Nonstring metadata key")
                public = replacement(name, pointer + "/@key", key=True)
                require(public not in result, "Sanitized key collision")
                result[public] = visit(child, pointer + "/" + name)
            return result
        if isinstance(item, list):
            return [visit(child, pointer + "/" + str(i)) for i, child in enumerate(item)]
        if isinstance(item, str):
            return replacement(item, pointer)
        finite(item)
        return item

    result = visit(value, "")
    public_safe(encoded(result), "sanitized metadata")
    return result, redactions


def selected_payload(folder, meta, index):
    """Existing packed viewer schema, without ICPC model/count constants.

    Consume every all-event chunk and independently check every row and zero.
    This function creates a value only; it does not write or declare completion.
    Native/truth group joining remains required in the unfinished exporter.
    """
    import geometry_events as geometry
    import hit_event_view as hits

    require(meta["model_id"] in MODELS and meta["primary_count"] == PRIMARY_COUNT
            and index["event_count"] == PRIMARY_COUNT, "Ring model/10K census required")
    columns = {table: ["raw_row_index", *schema]
               for table, schema in index["raw_columns"].items()}
    processes = {p["procid"]: p["name"] for p in index["processes"]}
    offsets = Counter()
    selected, evidence, ids = [], [], []
    require(len(index["chunks"]) == 100, "Exactly 100 all-event chunks required")
    for number, chunk in enumerate(index["chunks"]):
        name = f"events-{number * 100:05d}.json"
        require(chunk["file"] in (name, name + '.gz') and chunk["first"] == number * 100
                and chunk["count"] == 100, "Invalid all-event chunk identity")
        data = checked_chunk(folder, chunk)
        require(data["model"] == meta["model_id"] and data["first"] == number * 100
                and len(data["events"]) == 100, "Invalid all-event chunk schema")
        for position, event in enumerate(data["events"]):
            geometry.validate_event(event, number * 100 + position, offsets)
            require(set(event["tables"]) == set(columns), "Raw table census changed")
            for table, rows in event["tables"].items():
                require(all(set(row) == set(columns[table]) for row in rows), "Raw column loss")
            if not any(row["edep"] > 0 for row in event["tables"]["stp/germanium"]):
                continue
            packed = hits.pack(event, columns)
            require(exact(hits.unpack(packed, columns), event), "Lossy packed event, including signed zero")
            require(exact(read_json_bytes(encoded(packed)), packed), "JSON scalar/sign loss")
            selected.append(packed)
            ids.append(event["event_id"])
            evidence.append(hits.classify(event, processes, meta["grouping_policy"]["horizon_ns"]))
    require(dict(offsets) == {k: n for k, n in index["raw_rows"].items() if n}, "Raw row census mismatch")
    require(ids == index["ge_hit_ids"] and index["zero_ge_primaries"] == PRIMARY_COUNT - len(ids),
            "Positive/zero primary census mismatch")
    categories = {key: [{"event_id": e["event_id"], "group_id": g["group_id"]}
                        for e in evidence for g in e["groups"] if key in g["categories"]]
                  for key in hits.LABELS}
    lookup = {(e["event_id"], g["group_id"]): g for e in evidence for g in e["groups"]}
    representatives = {}
    for key, members in categories.items():
        highest = max((lookup[(m["event_id"], m["group_id"])]["source_photon_energy_keV"] or 0
                       for m in members), default=0)
        family = [m for m in members if abs(
            (lookup[(m["event_id"], m["group_id"])]["source_photon_energy_keV"] or 0) - highest
        ) <= hits.energy_tolerance(highest)]
        metric = "deposit_diameter_mm" if key == "compact" else "ge_energy_keV"
        ordered = sorted(family, key=lambda m: (
            lookup[(m["event_id"], m["group_id"])][metric], m["event_id"], m["group_id"]))
        representatives[key] = ordered[len(ordered) // 2] if ordered else None
    return {"schema_version": 1, "model": meta["model_id"], "event_ids": ids,
            "columns": columns, "events": selected, "evidence": evidence,
            "categories": categories, "representatives": representatives,
            "representative_rule": "Highest observed source-photon energy family within the declared numerical tolerance, then upper median deposit diameter for compact candidates or Ge energy otherwise; ties by original primary/group identity. Illustrative, not statistical typicality."}


def read_json_bytes(body):
    def invalid(value):
        raise ValueError("Nonfinite JSON value: " + value)
    return json.loads(body, parse_constant=invalid,
                      parse_int=lambda value: -0.0 if value == "-0" else int(value))


def checked(path, base, new=False):
    path, base = Path(os.path.abspath(path)), Path(os.path.abspath(base))
    require(path != base and path.is_relative_to(base), "Artifact escapes assigned root")
    for item in (path, *path.parents):
        require(not item.is_symlink() and not getattr(item, "is_junction", lambda: False)(), "Linked path refused")
    require(path.resolve() == path, "Linked path refused")
    require(not new or not path.exists(), "Existing output must be preserved")
    return path


def artifact_info(path):
    return {"sha256": digest(path), "bytes": Path(path).stat().st_size}


def byte_info(body):
    return {'sha256': hashlib.sha256(body).hexdigest(), 'bytes': len(body)}


def checked_chunk(folder, chunk):
    """Read only a registered JSON/gzip chunk, checking both byte domains."""
    name = chunk['file']; path = checked(Path(folder) / name, folder)
    require(name.endswith('.json') or name.endswith('.json.gz'), 'Unknown raw chunk encoding')
    body = path.read_bytes()
    require(byte_info(body)['sha256'] == chunk['sha256'], 'All-event chunk changed')
    if name.endswith('.gz'):
        require(chunk.get('encoding') == 'gzip' and chunk.get('gzip_mtime') == 0
                and chunk.get('bytes') == len(body) and len(body) >= 10
                and body[:3] == b'\x1f\x8b\x08' and body[4:8] == b'\0' * 4,
                'Unknown/non-deterministic raw gzip encoding')
        body = gzip.decompress(body)
        require(exact(byte_info(body), {'sha256': chunk.get('uncompressed_sha256'),
                'bytes': chunk.get('uncompressed_bytes')}), 'Raw gzip content changed')
    public_safe(body, name)
    return read_json_bytes(body)


def response_bytes(folder, name, record):
    """Original public bytes, either direct or from an explicitly pinned member.

    Rewritten HTML uses the archived original for scientific/source comparisons.
    There is no missing-file fallback: an absent direct artifact must be listed.
    """
    folder = Path(folder)
    delivery = record['response_record'].get('archive_delivery', {})
    rewrites = record['response_record'].get('delivery_rewrites', {})
    bound = delivery.get(name) or rewrites.get(name)
    if bound is None:
        return checked(folder / name, folder).read_bytes()
    require(bound['archive'] == 'ledgers.zip' and bound['member'] == name
            and exact(bound['original'], record['response_record']['archive_members'].get(name)),
            'Unregistered archive delivery')
    with zipfile.ZipFile(checked(folder / bound['archive'], folder)) as archive:
        body = archive.read(bound['member'])
    require(exact(byte_info(body), bound['original']), 'Archived public bytes changed')
    return public_safe(body, name)


def response_records(folder, name, record):
    for line in response_bytes(folder, name, record).splitlines():
        require(bool(line.strip()), 'Empty ledger row')
        value = read_json_bytes(line); finite(value)
        yield value


def write(path, body, public=True):
    if public:
        public_safe(body, Path(path).name)
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    with Path(path).open("xb") as stream:
        stream.write(body)


def write_json(path, value, public=True):
    write(path, encoded(value), public)


def source_inventory():
    return {name: artifact_info(checked(ROOT / name, ROOT)) for name in SOURCES}


def freeze():
    writer = read(checked(WRITER, WORK))
    inventory = source_inventory()
    require(writer["writer_stopped"] is True and writer["no_more_source_writes"] is True,
            "Wait for implementation writer to exit")
    for name, record in writer["source_records"].items():
        require(name in inventory and exact(record, inventory[name]), "Implementation writer source changed")
    record = {"kind": "ring_publication_source_freeze_v1", "source_records": inventory,
              "writer_receipt_sha256": digest(WRITER)}
    write_json(checked(FROZEN, WORK, new=True), record, public=False)
    return record


def frozen_sources():
    record = read(checked(FROZEN, WORK))
    require(record["kind"] == "ring_publication_source_freeze_v1"
            and exact(record["source_records"], source_inventory())
            and record["writer_receipt_sha256"] == digest(WRITER), "Exporter sources are not frozen")
    return record


def ge_terminal(directory):
    import ring_run as runner
    import ring_production as admission
    c = runner.config(directory)
    admitted = admission.verify(directory, "GeRC02")
    require(runner.equal(admitted, read(directory / "production-GeRC02-admission.json")),
            "Ge production pilot admission changed")
    verified = runner.verify(directory, phase="production", model="GeRC02")
    result = verified["results"]["production10000/GeRC02"]
    modeldir = directory / "production10000/GeRC02"
    complete_path = directory / "production-GeRC02-COMPLETE.json"
    complete = read(complete_path)
    require(complete.get("test_only") is not True
            and exact(complete["results"], {"production10000/GeRC02": result}), "Ge terminal result differs")
    commands = [
        runner.transport_command("prepare", "--model", "GeRC02", "--output", runner.ref(modeldir / "transport"),
                                 "--exporter", runner.EXPORTER, "--events", "10000", "--seed", str(runner.SEEDS["GeRC02"])),
        runner.transport_command("run", "--directory", runner.ref(modeldir / "transport")),
        runner.transport_command("extract", "--directory", runner.ref(modeldir / "transport"), "--chunk-size", "100"),
        runner.response_command(c, modeldir, c["production_native_failure_policy"]),
    ]
    paths, supervisors = [], set()
    for stage, argv in zip(("prepare", "transport", "extract", "response"), commands, strict=True):
        path = directory / "stages" / ("production10000-GeRC02-" + stage + ".json")
        record = read(path)
        require(record.get("test_only") is not True and record["status"] == "complete"
                and record["exit_code"] == 0 and record["command_argv"] == argv
                and record["name"] == "production10000-GeRC02-" + stage
                and record["source_sha256"] == c["source_sha256"]
                and type(record["child_pid"]) is int and record["child_pid"] > 0
                and type(record["supervisor_pid"]) is int and record["supervisor_pid"] > 0,
                "Actual Ge stage provenance differs: " + stage)
        supervisors.add(record["supervisor_pid"])
        require(complete["stage_receipt_sha256"]["stages/" + path.name] == digest(path), "Ge stage terminal binding differs")
        paths.append(path)
    require(len(supervisors) == 1, "Ge stage supervisors differ")
    supervisor = supervisors.pop()
    launch_path = directory / "production-GeRC02-launcher.json"
    exit_path = directory / "production-GeRC02-supervisor-exit.json"
    launch, exited = read(launch_path), read(exit_path)
    argv = [sys.executable, "-u", "-B", str(ROOT / "tools/ring_run.py"), "run", "--directory", str(directory),
            "--phase", "production", "--model", "GeRC02"]
    require(launch["command_argv"] == argv and launch["output_root"] == runner.ref(directory)
            and launch["source_sha256"] == c["source_sha256"]
            and launch["pid"] == exited["pid"] == complete["supervisor_pid"] == supervisor
            and exited["unresolved_child_intent"] is False, "Ge detached execution/exit differs")
    paths.extend((complete_path, launch_path, exit_path, directory / "config.json", directory / "config.sha256",
                  directory / "production-GeRC02-admission.json", modeldir / "VERIFIED.json"))
    return result, c["source_sha256"], paths


def inputs(model):
    # Only these registered terminal campaigns have an archived runtime basis.
    # Current compute admission keeps checking current source bytes separately.
    import ring_saved_basis
    return ring_saved_basis.publication_inputs(model)


def _checked_inputs(model):
    import ring_run as runner
    require(model in MODELS, "Unsupported ring detector")
    directory = checked(CAMPAIGN, ROOT / ".local")
    modeldir = directory / "production10000" / model
    if model == "GeRC02":
        result, sources, receipts = ge_terminal(directory)
    else:
        import km_ring_run as km
        verified = km.verify(directory, phase="production")
        result = verified["result"]
        c = km.configuration(directory)
        sources = c["source_sha256"]
        _, stages = km.verify_stages(directory, c, "production")
        receipts = [*stages, *(directory / name for name in (
            "km-production-COMPLETE.json", "km-production-launcher.json", "km-production-supervisor-exit.json",
            "km-config.json", "km-config.sha256", "config.json", "config.sha256", "km-pilot-COMPLETE.json"))]
    prepared, transport, manifest = runner.verify_transport(modeldir / "transport", model, PRIMARY_COUNT, runner.SEEDS[model])
    require(exact(read(modeldir / "transport/effective-model/model-contract.json"), prepared["model_contract"]),
            "Saved effective-model contract differs from prepared contract")
    native = read(modeldir / "response/run.json")
    envelope = read(modeldir / "response/ring-response.json")
    derivative = read(modeldir / "readout-inverted-v1/run.json") if model == "KMRC01_candidate" else None
    require(prepared["primary_count"] == native["counts"]["initial_primaries"]
            == result["counts"]["initial_primaries"] == PRIMARY_COUNT, "500/incomplete source cannot serve ring 10K")
    for item in (prepared, transport, native, envelope, manifest, result):
        require(item.get("test_only") is not True, "Test-only source refused")
    with (modeldir / "transport/truth.lh5").open("rb") as stream:
        require(stream.read(8) == b"\x89HDF\r\n\x1a\n", "Radiation source is not HDF5")
    pinned = [*receipts, modeldir / "transport/truth.lh5", modeldir / "transport/prepared.json",
              modeldir / "transport/run.json", modeldir / "transport/stream/manifest.json",
              modeldir / "response/run.json", modeldir / "response/ring-response.json"]
    for name in native["artifacts"]:
        pinned.append(checked(modeldir / "response" / name, modeldir / "response"))
    for name in (*prepared["files_sha256"], "effective-model/model-contract.json"):
        pinned.append(checked(modeldir / "transport" / name, modeldir / "transport"))
    pinned.extend(modeldir / "transport/stream" / row["file"] for row in manifest["chunks"])
    if derivative:
        pinned.append(modeldir / "readout-inverted-v1/run.json")
        pinned.extend(checked(modeldir / "readout-inverted-v1" / name, modeldir / "readout-inverted-v1")
                      for name in derivative["artifacts"])
    return {"model": model, "modeldir": modeldir, "prepared": prepared, "transport": transport,
            "stream": manifest, "native": native, "envelope": envelope, "derivative": derivative,
            "current": derivative or native, "result": result, "source_sha256": sources,
            "pins": {runner.ref(path): artifact_info(path) for path in pinned}}


def recheck_pins(context):
    for name, record in context["pins"].items():
        require(exact(artifact_info(checked(ROOT / name, ROOT)), record), "Saved input changed during export")


def scene_paths(model):
    return WORK / "build" / (model + "-scene-native.json"), WORK / "build" / (model + "-scene-receipt.json")


def scene(model, executable=NATIVE_EXECUTABLE):
    """Explicit native mesh inspection of a terminal model. No physics manager."""
    import ring_run as runner
    frozen = frozen_sources()
    context = inputs(model)
    executable = checked(executable, WORK / "build")
    require(executable == NATIVE_EXECUTABLE and executable.is_file(), "Use the assigned additive ring inspector")
    target, receipt_path = scene_paths(model)
    checked(target, WORK, new=True); checked(receipt_path, WORK, new=True)
    log = checked(WORK / "logs" / (model + "-scene.log"), WORK, new=True)
    gdml = context["modeldir"] / "transport/geometry.gdml"
    if os.name == "nt":
        def linux(path):
            require(str(path).lower().startswith("c:\\"), "Existing WSL path requires drive C")
            return "/mnt/c/" + path.as_posix()[3:]
        command = ["wsl.exe", "-d", "Ubuntu-24.04", "--cd", runner.linux_root(), "--exec", "bash", "-c",
                   'exec "$HOME/.pixi/bin/pixi" run --locked --no-install --manifest-path transport/pixi.toml "$@"',
                   "ring-scene", linux(executable), linux(gdml), linux(target)]
    else:
        command = [str(executable), str(gdml), str(target)]
    target.parent.mkdir(parents=True, exist_ok=True); log.parent.mkdir(parents=True, exist_ok=True)
    executable_info = artifact_info(executable)
    with log.open("x", encoding="utf-8", newline="\n") as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT, check=False)
    require(result.returncode == 0, "Native scene inspection failed; preserve output/log")
    import geometry_events as geometry
    native = read(target)
    geometry.validate_scene(native, read(context["modeldir"] / "transport/geometry-report.json"), context["prepared"])
    require(exact(frozen, frozen_sources()) and exact(executable_info, artifact_info(executable)), "Scene exporter source changed")
    recheck_pins(context)
    receipt = {"kind": "ring_saved_geometry_inspection_v1", "status": "complete", "model": model,
               "command_argv": command, "exit_code": 0, "radiation_calls": 0,
               "source_freeze_sha256": digest(FROZEN), "gdml_sha256": digest(gdml),
               "native_executable": executable_info, "native_source_sha256": digest(ROOT / "tools/ring_scene.cc"),
               "scene": artifact_info(target), "log_sha256": digest(log)}
    write_json(receipt_path, receipt, public=False)
    return receipt


def saved_scene(context):
    import geometry_events as geometry
    target, receipt_path = scene_paths(context["model"])
    receipt = read(checked(receipt_path, WORK))
    require(receipt["kind"] == "ring_saved_geometry_inspection_v1" and receipt["status"] == "complete"
            and receipt["model"] == context["model"] and receipt["radiation_calls"] == 0
            and receipt["exit_code"] == 0 and receipt["source_freeze_sha256"] in (digest(FROZEN), PREVIOUS_SCENE_FREEZE)
            and receipt["gdml_sha256"] == digest(context["modeldir"] / "transport/geometry.gdml")
            and receipt["native_source_sha256"] == digest(ROOT / "tools/ring_scene.cc")
            and exact(receipt["native_executable"], artifact_info(NATIVE_EXECUTABLE))
            and exact(receipt["scene"], artifact_info(target)), "Native ring mesh binding differs")
    value = read(target)
    geometry.validate_scene(value, read(context["modeldir"] / "transport/geometry-report.json"), context["prepared"])
    return value, artifact_info(receipt_path)


def raw(model):
    """Use the existing Linux HDF5 reader; never create a new environment."""
    import ring_run as runner
    frozen = frozen_sources(); context = inputs(model)
    target = checked(WORK / 'build/raw' / model, WORK, new=True)
    log = checked(WORK / 'logs' / (model + '-raw.log'), WORK, new=True)
    target.mkdir(parents=True); log.parent.mkdir(parents=True, exist_ok=True)
    require(os.name == 'nt', 'This explicit saved-reader entry uses the existing Windows/WSL environment')
    def linux(path):
        require(str(path).lower().startswith('c:\\'), 'Existing WSL input requires drive C')
        return '/mnt/c/' + path.as_posix()[3:]
    script = ('import sys,json,pathlib,h5py,numpy;sys.path.insert(0,"tools");import geometry_events as g;'
              'source=pathlib.Path(sys.argv[1]);meta=json.loads(pathlib.Path(sys.argv[2]).read_text());'
              'out=pathlib.Path(sys.argv[3]);index=g.export_raw(source,meta,out);'
              'g.write_json(out/"index.json",index);'
              'g.write_json(out/"runtime.json",{"python":sys.version,"h5py":h5py.__version__,"numpy":numpy.__version__})')
    source = context['modeldir'] / 'transport'
    command = ['wsl.exe', '-d', 'Ubuntu-24.04', '--cd', runner.linux_root(), '--exec', 'bash', '-c',
               'exec "$HOME/.pixi/bin/pixi" run --locked --no-install --manifest-path transport/pixi.toml "$@"',
               'saved-ring-raw', 'python', '-B', '-c', script, linux(source), linux(source / 'prepared.json'), linux(target)]
    with log.open('x', encoding='utf-8') as stream:
        result = subprocess.run(command, cwd=ROOT, stdout=stream, stderr=subprocess.STDOUT)
    require(result.returncode == 0, 'Saved HDF5 export failed; preserve raw derivative and log')
    recheck_pins(context); require(exact(frozen, frozen_sources()), 'Raw-export sources changed')
    record = {'kind': 'ring_saved_raw_export_v1', 'status': 'complete', 'model': model,
              'radiation_calls': 0, 'native_calls': 0, 'exit_code': 0, 'command_argv': command,
              'source_freeze_sha256': digest(FROZEN), 'raw_reader_sha256': digest(ROOT / 'tools/geometry_events.py'),
              'source_lh5_sha256': context['transport']['source_lh5_sha256'],
              'prepared_sha256': digest(source / 'prepared.json'), 'index': artifact_info(target / 'index.json'),
              'runtime': read(target / 'runtime.json'), 'log_sha256': digest(log)}
    write_json(target / 'COMPLETE.json', record, public=False)
    return record


def saved_raw(context, destination):
    """Copy every already-exported raw row after source/census/hash checks."""
    cache = checked(WORK / 'build/raw' / context['model'], WORK)
    record = read(cache / 'COMPLETE.json'); source = context['modeldir'] / 'transport'
    if record['source_freeze_sha256'] != digest(FROZEN):
        require(record['source_freeze_sha256'] == PREVIOUS_RAW_FREEZE
                and digest(cache / 'COMPLETE.json') == PREVIOUS_RAW_RECEIPTS.get(context['model']),
                'Unregistered historical raw-export receipt')
    require(record['kind'] == 'ring_saved_raw_export_v1' and record['status'] == 'complete'
            and record['model'] == context['model'] and record['exit_code'] == 0
            and record['radiation_calls'] == record['native_calls'] == 0
            and record['source_freeze_sha256'] in (digest(FROZEN), PREVIOUS_RAW_FREEZE)
            and record['raw_reader_sha256'] == digest(ROOT / 'tools/geometry_events.py')
            and record['source_lh5_sha256'] == context['transport']['source_lh5_sha256']
            and record['prepared_sha256'] == digest(source / 'prepared.json')
            and exact(record['index'], artifact_info(cache / 'index.json')), 'Saved raw-source binding differs')
    index = read(cache / 'index.json')
    require(index['event_count'] == PRIMARY_COUNT and len(index['chunks']) == 100,
            'Saved raw census must include all 10,000 initial decays')
    expected = {'index.json', 'runtime.json', 'COMPLETE.json'}
    for number, chunk in enumerate(index['chunks']):
        name = chunk['file']
        require(name == f'events-{number*100:05d}.json' and chunk['first'] == number*100
                and chunk['count'] == 100, 'Saved raw chunk identity differs')
        path = checked(cache / name, cache)
        require(digest(path) == chunk['sha256'], 'Saved raw chunk changed')
        expected.add(name); write(destination / name, path.read_bytes())
    require({p.name for p in cache.iterdir()} == expected, 'Saved raw file inventory differs')
    return index


def records(path):
    with Path(path).open(encoding="utf-8") as stream:
        for line in stream:
            require(bool(line.strip()), "Empty ledger row")
            value = read_json_bytes(line.encode())
            finite(value)
            yield value


def joined_groups(context, folder, index, positive):
    """Bind displayed groups to native truth, with original row order/delays."""
    truth = iter(records(context["modeldir"] / "response/truth.jsonl"))
    evidence = {e["event_id"]: e for e in positive["evidence"]}
    scalar_path = context["modeldir"] / ("readout-inverted-v1" if context["derivative"] else "response") / "scalars.jsonl"
    scalar = iter(records(scalar_path)); group_count = 0; pulse_keys = []
    for chunk in index["chunks"]:
        for event in checked_chunk(folder, chunk)["events"]:
            decay = next(truth, None); summary = next(scalar, None)
            require(decay is not None and summary is not None
                    and decay["event_id"] == summary["event_id"] == event["event_id"]
                    and summary["record_kind"] == "decay", "Truth/scalar/all-event identity mismatch")
            for table in ("vtx", "particles", "tracks"):
                require(exact(event["tables"][table], decay[table]), "Radiation truth raw row changed")
            expected = evidence.get(event["event_id"], {"groups": []})["groups"]
            require(len(expected) == len(decay["pulse_groups"]) == summary["pulse_count"], "Pulse grouping census mismatch")
            raw_rows = event["tables"]["stp/germanium"]
            require(exact(raw_rows, [step["raw"] for step in decay["steps"]]), "Native truth lost or changed a raw Ge row")
            positive_rows = {row["raw_row_index"]: row for row in raw_rows if row["edep"] > 0}
            require(set(positive_rows) == {step["raw_row_index"] for step in decay["steps"] if step["energy_keV"] > 0}, "Positive deposition row census differs")
            for group, native_group in zip(expected, decay["pulse_groups"], strict=True):
                pulse = next(scalar, None)
                require(pulse is not None and pulse["record_kind"] == "pulse"
                        and pulse["event_id"] == event["event_id"] and pulse["global_decay_id"] == decay["global_decay_id"]
                        and pulse["group_id"] == group["group_id"] == native_group["group_id"]
                        and pulse["raw_row_indices"] == group["ge_raw_row_indices"] == native_group["row_indices"]
                        and exact(pulse["origin_time_ns"], group["origin_time_ns"])
                        and exact(native_group["origin_time_ns"], group["origin_time_ns"]), "Display/native group rows or original clock differs")
                delays = [positive_rows[row]["time"] - group["origin_time_ns"] for row in group["ge_raw_row_indices"]]
                require(exact(delays, group["relative_delays_ns"]), "Display deposition delay changed")
                require(math.isclose(pulse["deposited_energy_keV"], group["ge_energy_keV"], rel_tol=1e-12, abs_tol=1e-12),
                        "Truth group energy changed")
                if pulse.get("status") == "native_transport_failed":
                    require(pulse["readout"] is None and pulse["final_induced_keV"] is None
                            and pulse["transport_flags"] is None, "Unknown native quantity fabricated")
                pulse_keys.append((event["event_id"], pulse["group_id"])); group_count += 1
    require(next(truth, None) is None and next(scalar, None) is None, "Extra native truth/scalar records")
    require(group_count == context["current"]["counts"]["groups"], "Native/positive group census differs")
    return pulse_keys


def histogram(scalars, counts, ionisation_energy_eV):
    bins = {stage: Counter() for stage in STAGES}
    one_keV_charge = 1000 / ionisation_energy_eV * 1.602176634e-19
    def add(stage, value):
        if value is None:
            return
        finite(value)
        require(type(value) in (int, float), "Invalid histogram energy")
        k = -1 if value < -1000 else 1000 if value >= 4000 else math.floor((value + 1000) / 5)
        bins[stage][k] += 1
    for record in scalars:
        if record["record_kind"] == "decay":
            add("deposited_per_decay", record["deposited_energy_keV"])
            continue
        add("deposited_per_group", record["deposited_energy_keV"])
        readout = record["readout"]
        if readout is None:
            continue
        add("native_terminal_charge", record["final_induced_keV"])
        add("window_charge", readout["final_charge_C"] / one_keV_charge)
        add("preamp_charge_equivalent", readout["preamp_peak_charge_equivalent_keV"])
        add("analog_shaped_equivalent", readout["analog_energy_keV"])
        add("accepted_peak_ADC", readout["reconstructed_energy_keV"])
    expected = {"deposited_per_decay": counts["initial_primaries"], "deposited_per_group": counts["groups"],
                "accepted_peak_ADC": counts["accepted"]}
    expected.update({stage: counts["groups"] - counts["native_failed_groups"] for stage in (
        "native_terminal_charge", "window_charge", "preamp_charge_equivalent", "analog_shaped_equivalent")})
    require(all(sum(bins[stage].values()) == n for stage, n in expected.items()), "Histogram stage population differs")
    rows = []
    for stage in sorted(bins):
        for k, n in sorted(bins[stage].items()):
            rows.append({"stage": stage, "bin": k, "lower_keV": None if k == -1 else -1000 + 5 * k,
                         "upper_keV": None if k == 1000 else -1000 + 5 * (k + 1), "count": n,
                         "per_initial_primary": n / counts["initial_primaries"],
                         "per_initial_decay": n / counts["initial_decays"] if counts["initial_decays"] else None,
                         "per_emitted_660_663_keV_photon": n / counts["line_photons"] if counts["line_photons"] else None,
                         "per_accepted_pulse": n / counts["accepted"] if counts["accepted"] else None})
    return {"bins": rows, "width_keV": 5, "normalization_denominators": counts,
            "note": "Raw stage counts with distinct denominators; native signed charge remains signed. Erec contains accepted pulses only. Numerical parcel variation is not physical energy resolution."}


def csv_bytes(columns, rows):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream, lineterminator="\n")
    writer.writerow(columns)
    for row in rows:
        writer.writerow(["" if row.get(key) is None else row[key] for key in columns])
    return stream.getvalue().encode()


def public_copy(source, target, bindings, metadata=False, binding_name=None):
    source = Path(source)
    body = source.read_bytes(); original = artifact_info(source)
    redactions = []
    if metadata:
        value, redactions = sanitized_metadata(read_json_bytes(body))
        body = encoded(value)
    write(target, body)
    bindings[binding_name or Path(target).name] = {"source": original, "public": artifact_info(target),
                                 "metadata_derivative": metadata, "redactions": redactions}


def zip_files(target, members):
    """Deterministic portable archive; members are already public-checked bytes."""
    checked(target, ROOT, new=True)
    Path(target).parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(target, "x", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for name, body in sorted(members.items()):
            require(type(name) is str and name and not name.startswith("/") and "\\" not in name
                    and all(part not in ("", ".", "..") for part in name.split("/")), "Unsafe ZIP member")
            public_safe(body, name)
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED; info.external_attr = 0o100644 << 16
            archive.writestr(info, body)
    return {name: {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
            for name, body in sorted(members.items())}


def archive_inventory(path):
    inventory = {}
    with zipfile.ZipFile(path) as archive:
        for info in archive.infolist():
            name = info.filename
            require(name not in inventory and not name.startswith("/") and "\\" not in name
                    and all(p not in ("", ".", "..") for p in name.split("/"))
                    and not info.flag_bits & 1 and info.compress_type in (0, 8)
                    and (info.external_attr >> 16) & 0o170000 != 0o120000, "Unsafe/duplicate archive member")
            body = public_safe(archive.read(info), name)
            inventory[name] = {"sha256": hashlib.sha256(body).hexdigest(), "bytes": len(body)}
    return inventory


def geometry_archive(context, target):
    import geometry_events as geometry
    directory = context["modeldir"] / "transport"
    bindings, members = {}, {}
    for name in geometry.ORIGINALS:
        source = directory / name; body = source.read_bytes(); redactions = []
        if source.suffix == ".json":
            value, redactions = sanitized_metadata(read_json_bytes(body)); body = encoded(value)
        public_safe(body, name)
        members[name] = body
        bindings[name] = {"source": artifact_info(source), "public_sha256": hashlib.sha256(body).hexdigest(),
                          "public_bytes": len(body), "metadata_derivative": source.suffix == ".json", "redactions": redactions}
    members["source-bindings.json"] = encoded({"kind": "ring_geometry_public_derivative_v1", "files": bindings,
        "note": "GDML and macro bytes are exact. JSON metadata has separate original/public bindings; removed private paths are never scientific edits."})
    return zip_files(target, members), bindings


def trace_svg(trace, xkey, series, title, unit):
    times = trace[xkey]
    require(times and all(len(values) == len(times) for _, values, _ in series), "Saved trace column length differs")
    finite(times)
    for _, values, _ in series:
        finite(values)
    lo, hi = min([0.0] + [v for _, values, _ in series for v in values]), max([0.0] + [v for _, values, _ in series for v in values])
    if lo == hi:
        hi = lo + 1
    first, last = min(times), max(times)
    require(last > first, "Saved trace lacks a time span")
    lines = []
    for label, values, color in series:
        points = " ".join(f"{35 + 640 * (t-first)/(last-first):.6f},{155 - 120 * (v-lo)/(hi-lo):.6f}"
                          for t, v in zip(times, values, strict=True))
        lines.append(f'<polyline fill="none" stroke="{color}" stroke-width="1.5" points="{points}"/>')
    zero = 155 - 120 * (0-lo)/(hi-lo)
    legend = " · ".join(html.escape(label) for label, _, _ in series)
    return (f'<figure><figcaption>{html.escape(title)} ({html.escape(unit)}): {legend}</figcaption>'
            f'<svg viewBox="0 0 700 185" role="img" aria-label="{html.escape(title)}">'
            f'<line x1="35" x2="675" y1="{zero:.6f}" y2="{zero:.6f}" stroke="#ccc"/>'
            + "".join(lines) + f'<text x="35" y="177" font-size="12">{first!r}–{last!r} ns; {lo!r}–{hi!r} {html.escape(unit)}</text></svg></figure>')


def response_page(model, current, scalar_path, trace_path):
    pulses = [r for r in records(scalar_path) if r["record_kind"] == "pulse"]
    first_keys = {(r["event_id"], r["group_id"]) for r in pulses[:4]}
    available = {}; total_traces = 0
    for trace in records(trace_path):
        key = trace["event_id"], trace["group_id"]
        total_traces += 1
        if key in first_keys:
            require(key not in available, "Duplicate trace identity")
            available[key] = trace
    sections = []
    for pulse in pulses[:4]:
        key = pulse["event_id"], pulse["group_id"]
        title = f'Event {key[0]} / group {key[1]}'
        if pulse["readout"] is None:
            require(key not in available, "Failed group has a fabricated trace")
            sections.append(f'<details><summary>{title}: native response unavailable</summary><pre>'
                            + html.escape(encoded(pulse).decode()) + '</pre></details>')
            continue
        require(key in available, "First-four source trace is missing")
        saved = available[key]; trace = saved["trace"]
        charge = [("Electronics input" if model == "KMRC01_candidate" else "Native signed charge",
                   trace["induced_charge_fC"], "#126b86")]
        current_series = [("Electronics input" if model == "KMRC01_candidate" else "Native signed current",
                           trace["current_nA"], "#126b86")]
        if model == "KMRC01_candidate":
            charge.insert(0, ("Raw native", saved["raw_native_induced_charge_fC"], "#aa4433"))
            current_series.insert(0, ("Raw native", saved["raw_native_current_nA"], "#aa4433"))
        graphs = trace_svg(trace, "time_ns", charge, "Signed induced charge", "fC")
        graphs += trace_svg(trace, "current_bin_start_ns", current_series, "Interval current", "nA")
        graphs += trace_svg(trace, "time_ns", [("CSA", trace["preamp_V"], "#634b92")], "Preamp", "V")
        graphs += trace_svg(trace, "time_ns", [("Analog shaper", trace["shaped_V"], "#4d8247")], "Shaped voltage", "V")
        r = pulse["readout"]
        fact = f'Accepted: {r["accepted"]}; peak ADC code: {r["adc_code"]}; reconstructed energy: {r["reconstructed_energy_keV"]!r} keV.'
        sections.append(f'<details><summary>{title}</summary><p>{html.escape(fact)}</p>{graphs}'
                        '<p>These bounded saved display samples retain the original interval definitions in traces.jsonl. '
                        'The peak ADC is one code; analog samples are not waveform digitization.</p></details>')
    counts = current["counts"]
    label = "GeRC02 Li50min" if model == "GeRC02" else "KMRC01 candidate: fixed −1 electronics wiring"
    wiring_note = ('<p>The raw native charge stays negative. A fixed −1 wiring factor precedes unchanged electronics, '
                   'with one independently injected negative 500 keV calibration. '
                   '<a href="original-native/summary.html">Original native readout and rejection history</a> are retained.</p>'
                   if model == "KMRC01_candidate" else '')
    page = ('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>' + html.escape(label) + ' response</title><style>body{font:16px/1.5 system-ui;max-width:1050px;margin:auto;padding:20px;overflow-wrap:anywhere}svg{width:100%;height:auto}pre{white-space:pre-wrap}summary{cursor:pointer}figure{margin:16px 0}nav{display:flex;flex-wrap:wrap;gap:12px}</style>'
            '<h1>' + html.escape(label) + ': saved 10,000-decay response</h1>'
            '<p>Functional engineering example: synthetic isolated electronics, no measured hardware, calibrated Li CCE, physical FWHM, activity, pileup or experimental fit. Numerical parcel variation is not physical resolution. Native failures retain null quantities.</p>'
            + wiring_note + '<nav><a href="run.json">Settings, calibration and provenance</a><a href="scalars.csv">All primaries and pulse scalars</a>'
            '<a href="truth.jsonl">Complete deposition truth</a><a href="endpoints.csv">All native endpoints</a>'
            '<a href="histograms.csv">Stage histograms</a><a href="signals.csv">Saved raw signed native signals</a>'
            '<a href="traces.jsonl">Saved traces</a><a href="ledgers.zip">Complete public ledger archive</a></nav>'
            '<pre>' + html.escape(encoded(counts).decode()) + '</pre>'
            '<p>Trace examples follow the first four pulse groups in original census order. A failed group gets no replacement waveform. '
            'Zero-deposit primaries remain in the truth and scalar ledgers. The native signals download follows the recorded charge-CSV policy; no missing Ge waveforms are synthesized.</p>'
            + ''.join(sections) + '</html>')
    return page.encode(), {"selection": "first 4 pulse groups in original census order", "source_trace_records": total_traces,
                          "displayed_trace_keys": [list(k) for k in sorted(available)],
                          "displayed_group_keys": [[r["event_id"], r["group_id"]] for r in pulses[:4]]}


def response(context, destination):
    source = context["modeldir"] / "response"; destination.mkdir(parents=True)
    native = context["native"]; original = destination / "original-native" if context["derivative"] else destination
    original.mkdir(exist_ok=True)
    bindings = {}
    expected = set(LEDGER_NAMES) | ({"native-failures.jsonl"} if native["counts"]["native_failed_groups"] else set())
    require(set(native["artifacts"]) == expected, "Unknown native artifact inventory")
    for name in sorted(expected | {"ring-response.json"}):
        if name == "summary.html" and not context["derivative"]:
            public_copy(source / name, destination / "original-summary.html", bindings)
        else:
            public_copy(source / name, original / name, bindings, metadata=name in METADATA,
                        binding_name=("original-native/" + name) if context["derivative"] else name)
    native_metadata, native_redactions = sanitized_metadata(native)
    write_json(original / ("native-source-run.json" if not context["derivative"] else "run.json"),
               {"kind": "ring_public_source_metadata_v1", "source_sha256": digest(source / "run.json"),
                "source": native_metadata, "redactions": native_redactions,
                "note": "Source artifact hashes bind local originals; public metadata derivatives have separate hashes."})
    current_path = source
    if context["derivative"]:
        current_path = context["modeldir"] / "readout-inverted-v1"
        for name in ("truth.csv", "truth.jsonl", "endpoints.csv", "endpoints.jsonl", "signals.csv", "profile.json", "profile-input.json", "readout-config.json"):
            public_copy(source / name, destination / name, bindings)
        if "native-failures.jsonl" in expected:
            public_copy(source / "native-failures.jsonl", destination / "native-failures.jsonl", bindings)
        for name in context["derivative"]["artifacts"]:
            public_copy(current_path / name, destination / name, bindings)
        scalar_rows = ({**row, "record_json": encoded(row).decode().rstrip("\n")} for row in records(current_path / "scalars.jsonl"))
        write(destination / "scalars.csv", csv_bytes(SCALAR_COLUMNS, scalar_rows))
        h = histogram(records(current_path / "scalars.jsonl"), context["current"]["counts"], native["ionisation_energy_eV"])
        write_json(destination / "histograms.json", h)
        histogram_columns = ("stage", "bin", "lower_keV", "upper_keV", "count", "per_initial_primary",
                             "per_initial_decay", "per_emitted_660_663_keV_photon", "per_accepted_pulse")
        write(destination / "histograms.csv", csv_bytes(histogram_columns, h["bins"]))
    else:
        saved = read(source / "histograms.json")
        regenerated = histogram(records(source / "scalars.jsonl"), native["counts"], native["ionisation_energy_eV"])
        columns = ("stage", "bin", "lower_keV", "upper_keV", "count")
        require([{k: row[k] for k in columns} for row in saved["bins"]] ==
                [{k: row[k] for k in columns} for row in regenerated["bins"]], "Native saved histogram census differs")
    current, redactions = sanitized_metadata(context["current"])
    public_metadata = {"kind": "ring_public_response_v1", "model": context["model"], "current": current,
        "model_contract": sanitized_metadata(context["prepared"]["model_contract"])[0],
        "source_native_report_sha256": digest(source / "run.json"),
        "source_ring_envelope_sha256": digest(source / "ring-response.json"),
        "source_derivative_report_sha256": digest(current_path / "run.json") if context["derivative"] else None,
        "native_counts": native["counts"], "current_counts": context["current"]["counts"],
        "readout_wiring": context["derivative"]["wiring"] if context["derivative"] else {"factor": 1, "stage": "native signed charge -> electronics input"},
        "calibration": context["current"]["calibration"], "source_artifacts": native["artifacts"],
        "metadata_redactions": redactions, "source_public_bindings": bindings,
        "csv_units": {"signals.csv": {"time_since_origin_ns": "ns", "induced_equivalent_energy_keV": "signed native equivalent keV"},
            "readout-input.csv": {"time_since_origin_ns": "ns", "charge_keV_columns": "equivalent keV", "charge_fC_columns": "fC", "current_nA_columns": "nA"},
            "scalars.csv": "Column names declare ns/keV; record_json retains all original quantities/units/flags/nulls.",
            "endpoints.csv": "position_mm:mm; deposition_delay_ns/original_time_ns/origin_time_ns:ns; parcel_weight_keV and deposited_energy_keV:keV; seed_uint64:string."},
        "limitations": OMISSIONS,
        "archive_scope": "All public response files, including full truth/scalar/endpoint ledgers and available saved signals/traces. Raw LH5 and field caches excluded."}
    page, examples = response_page(context["model"], context["current"], current_path / "scalars.jsonl", current_path / "traces.jsonl")
    public_metadata["trace_examples"] = examples
    write(destination / "summary.html", page)
    write_json(destination / "run.json", public_metadata)
    members = {path.relative_to(destination).as_posix(): path.read_bytes()
               for path in sorted(destination.rglob("*")) if path.is_file()}
    archive = zip_files(destination / "ledgers.zip", members)
    return {"summary": destination.name + "/summary.html", "counts": context["current"]["counts"],
            "archive_members": archive, "source_native_artifacts": native["artifacts"],
            "trace_examples": examples, "current_report": artifact_info(destination / "run.json")}


def dataset_binding(context, terminal_sha256):
    """A real per-model saved dataset identity, independent of old campaigns."""
    modeldir = context["modeldir"]; contract = context["prepared"]["model_contract"]
    return {"kind": "ring_model_saved_dataset_binding_v1", "model_id": context["model"],
            "variant_id": contract["variant_id"], "primary_count": PRIMARY_COUNT,
            "model_original_sha256": contract["source_model_sha256"],
            "model_effective_sha256": contract["effective_model_sha256"],
            "raw_lh5_sha256": context["transport"]["source_lh5_sha256"],
            "geometry_gdml_sha256": digest(modeldir / "transport/geometry.gdml"),
            "prepared_sha256": digest(modeldir / "transport/prepared.json"),
            "stream_manifest_sha256": digest(modeldir / "transport/stream/manifest.json"),
            "native_report_sha256": digest(modeldir / "response/run.json"),
            "ring_response_sha256": digest(modeldir / "response/ring-response.json"),
            "derivative_report_sha256": digest(modeldir / "readout-inverted-v1/run.json") if context["derivative"] else None,
            "readout_profile_sha256": context["native"]["profile_sha256"],
            "readout_wiring_factor": -1 if context["derivative"] else 1,
            "terminal_receipt_sha256": terminal_sha256}


def build(output=WORK / "bundle"):
    """One no-clobber saved-data export of both independently terminal 10K cases."""
    import geometry_events as geometry
    import hit_event_view as hits
    frozen = frozen_sources()
    output = checked(output, WORK, new=True)
    require(output == WORK / "bundle", "Use the single assigned ring bundle root")
    require(not (CAMPAIGN / ".supervisor.lock").exists(), "Scientific supervisor must exit before bundle export")
    contexts = {model: inputs(model) for model in MODELS}
    meshes = {model: saved_scene(context) for model, context in contexts.items()}
    terminal_pins = {"GeRC02": digest(CAMPAIGN / "production-GeRC02-COMPLETE.json"),
                     "KMRC01_candidate": digest(CAMPAIGN / "km-production-COMPLETE.json")}
    campaign_hash = hashlib.sha256(encoded(terminal_pins)).hexdigest()
    manifest = {"kind": "ring_saved_publication_v1", "status": "complete", "schema_version": 1,
        "models": {}, "files": {}, "source_records": frozen["source_records"],
        "source_freeze_sha256": digest(FROZEN), "writer_receipt_sha256": frozen["writer_receipt_sha256"],
        "campaign_binding_sha256": campaign_hash, "input_pins": {"campaign_binding": campaign_hash},
        "campaign_binding": {"kind": "hash_of_model_terminal_receipt_map_v1", "terminal_sha256": terminal_pins,
                             "note": "This binds two separate production campaigns; it is not a fabricated joint run.json."},
        "serialization": {"raw_reader": "unchanged geometry_events.export_raw", "all_event_chunks": 100,
                          "primaries_per_chunk": 100, "numeric_policy": "Original integer and binary64 values, including signed zero; no event sampling or precision reduction.",
                          "packed_reader": "unchanged hit_event_view pack/unpack/classify", "gzip_mtime": 0},
        "category_labels": hits.LABELS, "method": hits.METHOD,
        "limitations": OMISSIONS, "runtime": {"export_python": sys.version},
        "upstream": sanitized_metadata(read(ROOT / "transport/cryostat-source.json"))[0],
        "upstream_source_sha256": digest(ROOT / "transport/cryostat-source.json")}
    output.mkdir(parents=True)
    for model, context in contexts.items():
        destination = output / model; destination.mkdir()
        meta = context["prepared"]; source = context["modeldir"] / "transport"
        index = saved_raw(context, destination)
        require(index["event_count"] == PRIMARY_COUNT and len(index["chunks"]) == 100
                and index["zero_ge_primaries"] == context["current"]["counts"]["zero_deposit_primaries"]
                and index["raw_rows"]["stp/germanium"] == context["transport"]["validation"]["ge_rows"], "Raw/terminal census differs")
        positive = selected_payload(destination, meta, index)
        groups = joined_groups(context, destination, index, positive)
        payload = encoded(positive)
        require(exact(read_json_bytes(payload), positive), "Packed JSON precision/sign loss")
        write(destination / "selected.json", payload)
        write(destination / "selected.json.gz", gzip.compress(payload, compresslevel=9, mtime=0), public=False)
        require(gzip.decompress((destination / "selected.json.gz").read_bytes()) == payload, "Gzip is not lossless")
        archive_members, original_bindings = geometry_archive(context, destination / "originals.zip")
        native, scene_receipt = meshes[model]
        scenario = sanitized_metadata(read(source / "scenario.json"))[0]
        native.update({"model": model, "source_position_global_mm": meta["source_position_global_mm"],
            "coordinate_transform": meta["coordinate_transform"], "scenario": scenario,
            "material_tables": meta["material_tables"], "mounting_contract": meta["mounting_contract"],
            "omissions": OMISSIONS, "raw_lh5_sha256": context["transport"]["source_lh5_sha256"],
            "originals_sha256": {name: data["source"]["sha256"] for name, data in original_bindings.items()},
            "public_originals_sha256": {name: data["public_sha256"] for name, data in original_bindings.items()},
            "raw_software_versions": context["transport"]["versions"], "seed": meta["seed"], "event_index": index})
        write_json(destination / "scene.json", native)
        response_record = response(context, destination / "response")
        source_pins, redactions = sanitized_metadata(context["pins"])
        computation, source_redactions = sanitized_metadata(context["source_sha256"])
        contract = sanitized_metadata(meta["model_contract"])[0]
        dataset = dataset_binding(context, terminal_pins[model])
        manifest["models"][model] = {"label": "GeRC02 Li50min" if model == "GeRC02" else "KMRC01 candidate",
            "model_id": model, "variant_id": contract["variant_id"], "qualification": contract["qualification"],
            "model_contract": contract, "model_original_sha256": contract["source_model_sha256"],
            "model_effective_sha256": contract["effective_model_sha256"], "scene": model + "/scene.json",
            "selected": model + "/selected.json.gz", "selected_count": len(positive["event_ids"]),
            "source_scene_sha256": digest(destination / "scene.json"), "category_group_counts": {k: len(v) for k, v in positive["categories"].items()},
            "dataset_binding": dataset, "dataset_binding_sha256": hashlib.sha256(encoded(dataset)).hexdigest(),
            "originals": model + "/originals.zip", "originals_archive_members": archive_members,
            "event_count": index["event_count"], "ge_hit_count": len(index["ge_hit_ids"]),
            "zero_ge_primaries": index["zero_ge_primaries"], "raw_rows": index["raw_rows"],
            "raw_lh5_sha256": context["transport"]["source_lh5_sha256"], "native_scene_receipt": scene_receipt,
            "raw_export_receipt": artifact_info(WORK / 'build/raw' / model / 'COMPLETE.json'),
            "raw_export_runtime": read(WORK / 'build/raw' / model / 'runtime.json'),
            "response": model + "/response/summary.html", "response_report": model + "/response/run.json",
            "response_record": response_record, "group_count": len(groups),
            "counts": context["current"]["counts"], "original_native_counts": context["native"]["counts"],
            "readout_wiring": context["derivative"]["wiring"] if context["derivative"] else {"factor": 1},
            "calibration": context["current"]["calibration"], "source_input_pins": source_pins,
            "computational_dependency_sha256": computation, "source_path_redactions": redactions + source_redactions,
            "input_pin_map_sha256": hashlib.sha256(encoded(context["pins"])).hexdigest(),
            "computational_inventory_sha256": hashlib.sha256(encoded(context["source_sha256"])).hexdigest()}
    write(output / "README.txt", (
        "Saved ring 10K engineering data: GeRC02 Li50min and unchanged KMRC01 candidate.\n"
        "Each detector has all 10,000 initial Cs137 identities, including zeros and unknown native responses.\n"
        "scene.json and 100 event chunks feed the maintained GeSignal viewer; selected.json.gz retains every Ge-positive primary.\n"
        "response/summary.html shows the original first-four-group policy; full public ledgers and available signed signals are downloadable.\n"
        "KM current electronics uses fixed -1 wiring and separate negative injection; original-native retains the original readout and negative signals.\n"
        "JSON metadata is explicitly sanitized and separately source/public hash-bound. No radiation, SSD or electronics was rerun.\n"
        "Serve this bundle on localhost for fetch-based viewing. No external frontend libraries are required.\n"
    ).encode())
    require(exact(frozen, frozen_sources()), "Source changed during export; preserve incomplete bundle")
    for context in contexts.values():
        recheck_pins(context)
    for path in sorted(output.rglob("*")):
        if path.is_file():
            manifest["files"][path.relative_to(output).as_posix()] = artifact_info(path)
    pending = output / "manifest.pending.json"
    write_json(pending, manifest)
    validate_bundle(output, check_local=True, _manifest_name="manifest.pending.json")
    require(exact(frozen, frozen_sources()), "Source changed before completion; preserve pending bundle")
    checked(output / "manifest.json", output, new=True)
    os.rename(pending, output / "manifest.json")
    return manifest


def validate_response(folder, record):
    value = read(folder / "run.json")
    require(value["kind"] == "ring_public_response_v1" and value["current_counts"] == record["counts"]
            and value["native_counts"] == record["original_native_counts"], "Public response summary differs")
    dataset = record["dataset_binding"]
    require(value["source_native_report_sha256"] == dataset["native_report_sha256"]
            and value["source_ring_envelope_sha256"] == dataset["ring_response_sha256"]
            and value["source_derivative_report_sha256"] == dataset["derivative_report_sha256"], "Response dataset identity differs")
    scalars = list(records(folder / "scalars.jsonl")); decays = [s for s in scalars if s["record_kind"] == "decay"]
    pulses = [s for s in scalars if s["record_kind"] == "pulse"]
    require(len(decays) + len(pulses) == len(scalars), "Unknown public scalar record kind")
    counts = record["counts"]
    require([s["event_id"] for s in decays] == list(range(PRIMARY_COUNT))
            and all(s["global_decay_id"] == s["event_id"] for s in decays), "Public full primary census differs")
    require(len(pulses) == counts["groups"] and len({(s["event_id"], s["group_id"]) for s in pulses}) == len(pulses),
            "Public group census differs")
    require(sum(s["zero_deposit"] for s in decays) == counts["zero_deposit_primaries"]
            and sum(s["accepted"] for s in pulses) == counts["accepted"], "Public zero/accepted counts differ")
    failures = [s for s in pulses if s.get("status") == "native_transport_failed"]
    require(len(failures) == counts["native_failed_groups"] and all(s["readout"] is None and s["final_induced_keV"] is None
            and s["transport_flags"] is None for s in failures), "Public native failure/null accounting differs")
    require(counts["rejected"] == counts["native_failed_groups"] + counts["readout_rejected"]
            and counts["accepted"] + counts["rejected"] == counts["groups"], "Public rejection populations differ")
    with io.StringIO(response_bytes(folder, 'scalars.csv', record).decode('utf-8'), newline='') as stream:
        csvrows = list(csv.DictReader(stream))
    require(len(csvrows) == len(scalars) and all(exact(read_json_bytes(row["record_json"].encode()), scalar)
            for row, scalar in zip(csvrows, scalars, strict=True)), "Scalar CSV/JSONL precision or flag loss")
    truth = iter(response_records(folder, 'truth.jsonl', record))
    pulse_count = 0
    for decay in decays:
        event = next(truth, None)
        require(event is not None and event["event_id"] == event["global_decay_id"] == decay["event_id"]
                and len(event["pulse_groups"]) == decay["pulse_count"], "Public truth census differs")
        pulse_count += len(event["pulse_groups"])
    require(next(truth, None) is None and pulse_count == counts["groups"], "Public truth/group totals differ")
    h = histogram(scalars, counts, value["current"].get("ionisation_energy_eV", value["calibration"]["ionisation_energy_eV"]))
    saved = read(folder / "histograms.json")
    numeric = ("stage", "bin", "lower_keV", "upper_keV", "count")
    require(saved["normalization_denominators"] == counts
            and [{k: row[k] for k in numeric} for row in saved["bins"]] == [{k: row[k] for k in numeric} for row in h["bins"]],
            "Public histogram stage census differs")
    require(archive_inventory(folder / "ledgers.zip") == record["response_record"]["archive_members"], "Ledger archive inventory differs")
    for name, binding in value["source_public_bindings"].items():
        require(exact(byte_info(response_bytes(folder, name, record)), binding["public"]), "Public source derivative binding differs")
        if not binding["metadata_derivative"]:
            require(exact(binding["source"], binding["public"]), "Scientific source bytes changed")


def validate_bundle(folder, check_local=False, _manifest_name="manifest.json"):
    import geometry_events as geometry
    import hit_event_view as hits
    folder = checked(folder, ROOT)
    require(_manifest_name in ("manifest.json", "manifest.pending.json"), "Unknown internal manifest name")
    manifest = read(folder / _manifest_name)
    require(manifest["kind"] == "ring_saved_publication_v1" and manifest["schema_version"] == 1
            and manifest["status"] == "complete" and set(manifest["models"]) == set(MODELS), "Incomplete ring bundle")
    require(manifest["category_labels"] == hits.LABELS and manifest["method"] == hits.METHOD,
            "Classification labels/method differ from frozen reader")
    require(exact(manifest["source_records"], source_inventory())
            or digest(folder / _manifest_name) == FULL_BUNDLE_MANIFEST,
            "Publication source inventory changed")
    actual = {p.relative_to(folder).as_posix() for p in folder.rglob("*") if p.is_file()}
    require(actual == set(manifest["files"]) | {_manifest_name}, "Public file census differs")
    for name, expected in manifest["files"].items():
        path = checked(folder / name, folder)
        require(exact(artifact_info(path), expected), "Public artifact changed: " + name)
        if path.suffix == ".zip":
            archive_inventory(path)
        elif path.suffix == ".gz":
            public_safe(gzip.decompress(path.read_bytes()), name)
        else:
            public_safe(path.read_bytes(), name)
    public_safe(encoded(manifest), "manifest.json")
    if 'packaging' in manifest:
        validate_package_bindings(folder, manifest)
    binding = manifest["campaign_binding"]["terminal_sha256"]
    require(hashlib.sha256(encoded(binding)).hexdigest() == manifest["campaign_binding_sha256"]
            == manifest["input_pins"]["campaign_binding"], "Campaign binding differs")
    for model, record in manifest["models"].items():
        require(record["model_id"] == model and record["event_count"] == PRIMARY_COUNT
                and record["scene"] == model + "/scene.json" and record["selected"] == model + "/selected.json.gz",
                "Public model/census contract differs")
        require(record["source_scene_sha256"] == manifest["files"][record["scene"]]["sha256"], "Positive/assembly scene binding differs")
        dataset = record["dataset_binding"]
        require(hashlib.sha256(encoded(dataset)).hexdigest() == record["dataset_binding_sha256"]
                and dataset["model_id"] == model and dataset["variant_id"] == record["variant_id"]
                and dataset["primary_count"] == PRIMARY_COUNT and dataset["terminal_receipt_sha256"] == binding[model]
                and dataset["raw_lh5_sha256"] == record["raw_lh5_sha256"]
                and dataset["model_original_sha256"] == record["model_original_sha256"]
                and dataset["model_effective_sha256"] == record["model_effective_sha256"], "Per-model dataset binding differs")
        scene_value = read(folder / record["scene"]); index = scene_value["event_index"]
        require(scene_value["model"] == model and scene_value["raw_lh5_sha256"] == record["raw_lh5_sha256"]
                and index["raw_rows"] == record["raw_rows"] and index["event_count"] == PRIMARY_COUNT, "Scene/source census differs")
        require(archive_inventory(folder / record["originals"]) == record["originals_archive_members"], "Geometry archive changed")
        with zipfile.ZipFile(folder / record["originals"]) as archive:
            prepared = read_json_bytes(archive.read("prepared.json")); report = read_json_bytes(archive.read("geometry-report.json"))
            geometry.validate_scene(scene_value, report, prepared)
            bindings = read_json_bytes(archive.read("source-bindings.json"))["files"]
            for name, bound in bindings.items():
                body = archive.read(name)
                require(hashlib.sha256(body).hexdigest() == bound["public_sha256"]
                        and scene_value["originals_sha256"][name] == bound["source"]["sha256"]
                        and scene_value["public_originals_sha256"][name] == bound["public_sha256"], "Original/public geometry bindings differ")
        positive = selected_payload(folder / model, prepared, index)
        require(("packaging" in manifest or (folder / model / "selected.json").read_bytes() == encoded(positive))
                and gzip.decompress((folder / record["selected"]).read_bytes()) == encoded(positive)
                and len(positive["event_ids"]) == record["selected_count"] == record["ge_hit_count"]
                and index["zero_ge_primaries"] == record["zero_ge_primaries"] == record["counts"]["zero_deposit_primaries"],
                "Selected record/classification/zero census differs")
        require(record["category_group_counts"] == {key: len(value) for key, value in positive["categories"].items()}
                and sum(len(value["groups"]) for value in positive["evidence"]) == record["group_count"] == record["counts"]["groups"],
                "Positive classification/native group census differs")
        validate_response(folder / model / "response", record)
        if check_local:
            context = inputs(model)
            require(exact(dataset, dataset_binding(context, binding[model])), "Dataset source binding differs")
            joined_groups(context, folder / model, index, positive)
            for name in context["native"]["artifacts"]:
                if name in METADATA or name == "summary.html":
                    continue
                public = folder / model / "response" / ("original-native" if context["derivative"] else "") / name
                relative = public.relative_to(folder / model / 'response').as_posix()
                require(byte_info(response_bytes(folder / model / 'response', relative, record))['sha256']
                        == context["native"]["artifacts"][name], "Native science export changed")
            if context["derivative"]:
                for name, expected in context["derivative"]["artifacts"].items():
                    require(byte_info(response_bytes(folder / model / 'response', name, record))['sha256'] == expected,
                            "KM derivative science export changed")
            require(record["counts"] == context["current"]["counts"], "Current completed source counts differ")
    return manifest


def package_summary(body, archive_only, original_native=False):
    """Change delivery links only; existing plot coordinates/text stay intact."""
    page = body.decode('utf-8')
    if original_native:
        # The archived original remains exact and browsable after extraction.
        # Its historical standalone links otherwise escape this delivered set.
        return ('<!doctype html><html lang="en"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width,initial-scale=1">'
            '<title>Original KM native response</title><h1>Original KM native response</h1>'
            '<p>The original signed native charge and original positive-peak rejection history are preserved. '
            'The original readout accepted 0 of 231 pulse groups. The current fixed −1 wiring is a separate derivative.</p>'
            '<nav><a href="run.json">Original settings and counts</a> · '
            '<a href="signals.csv">Original signed native signals</a> · '
            '<a href="scalars.jsonl">All original primary and group scalars</a> · '
            '<a href="../ledgers.zip">Complete original response, original HTML and ledgers (ZIP)</a></nav>'
            '<p>Extract the complete ZIP to inspect original-native/summary.html with its original local links.</p>'
            '</html>').encode('utf-8')
    replaced = set()
    def link(match):
        name = match.group(1)
        if name not in archive_only:
            return match.group(0)
        replaced.add(name)
        return 'href="ledgers.zip"'
    page = re.sub(r'href="([^"]+)"', link, page)
    note = ('<p>Complete truth, endpoints, scalar CSV, histogram CSV and saved traces are delivered byte-for-byte '
            'inside the complete ledger ZIP; these download links open that ZIP. Direct signed signals, '
            'JSONL scalars and JSON histograms remain available.</p>')
    require('</nav>' in page, 'Response page download navigation missing')
    page = page.replace('</nav>', '</nav>' + note, 1)
    require(not any('href="' + name + '"' in page for name in archive_only), 'Archive-only link remains')
    return page.encode('utf-8')


def delivery_map(archive_members):
    return {name: {'archive': 'ledgers.zip', 'member': name, 'original': info}
            for name, info in archive_members.items() if name not in DIRECT_RESPONSE}


def package_source(folder, manifest):
    binding = manifest['packaging']['source_manifest']
    require(binding['file'] == 'packaging-source-manifest.json'
            and binding['sha256'] == FULL_BUNDLE_MANIFEST, 'Unknown packaging source')
    path = checked(Path(folder) / binding['file'], folder)
    require(exact(artifact_info(path), {'sha256': binding['sha256'], 'bytes': binding['bytes']}),
            'Packaging source manifest changed')
    source = read(path)
    require(source['kind'] == 'ring_saved_publication_v1' and source['status'] == 'complete'
            and 'packaging' not in source and set(source['models']) == set(MODELS),
            'Packaging source is not the registered full export')
    require(exact(manifest['packaging']['source_records'], source['source_records']),
            'Packaging producer inventory changed')
    return source


def validate_package_bindings(folder, manifest):
    """Verify each permitted delivery change against the pinned full manifest."""
    folder = Path(folder); source = package_source(folder, manifest)
    packaging = manifest['packaging']
    require(packaging['kind'] == 'ring_lossless_web_package_v1'
            and packaging['scientific_recomputation'] == 0,
            'Unknown package format')
    # Whole scientific model/campaign metadata stays exactly original.
    mutable_top = {'files', 'models', 'source_records', 'source_freeze_sha256', 'writer_receipt_sha256'}
    require(set(manifest) == set(source) | {'packaging'}
            and all(exact(manifest[key], value) for key, value in source.items() if key not in mutable_top),
            'Packaging changed campaign/scientific metadata')
    expected_files = dict(source['files']); expected_files['packaging-source-manifest.json'] = {
        'sha256': FULL_BUNDLE_MANIFEST, 'bytes': packaging['source_manifest']['bytes']}
    gzip_count = 0
    for model in MODELS:
        original = source['models'][model]; current = manifest['models'][model]
        require(set(current) == set(original)
                and all(exact(current[key], value) for key, value in original.items()
                        if key not in ('source_scene_sha256', 'response_record')),
                'Packaging changed detector/scientific metadata')
        selected_name = model + '/selected.json'
        selected_bytes = gzip.decompress((folder / current['selected']).read_bytes())
        require(exact(byte_info(selected_bytes), source['files'][selected_name])
                and not (folder / selected_name).exists(), 'Selected gzip/source binding changed')
        expected_files.pop(selected_name)
        scene_name = original['scene']; scene = read(folder / scene_name)
        scene_original = dict(scene); index = dict(scene['event_index']); originals = []
        for number, chunk in enumerate(index['chunks']):
            name = f'events-{number * 100:05d}.json'; old_name = model + '/' + name
            require(chunk['file'] == name + '.gz' and chunk['encoding'] == 'gzip'
                    and chunk['gzip_mtime'] == 0 and chunk['first'] == number * 100 and chunk['count'] == 100
                    and exact({'sha256': chunk['uncompressed_sha256'], 'bytes': chunk['uncompressed_bytes']},
                              source['files'][old_name]), 'Raw chunk source binding changed')
            require(chunk['sha256'] == manifest['files'][old_name + '.gz']['sha256']
                    and chunk['bytes'] == manifest['files'][old_name + '.gz']['bytes'], 'Raw gzip file binding differs')
            checked_chunk(folder / model, chunk)
            old_chunk = {key: value for key, value in chunk.items()
                         if key not in ('encoding', 'gzip_mtime', 'bytes', 'uncompressed_sha256', 'uncompressed_bytes')}
            old_chunk['file'] = name; old_chunk['sha256'] = chunk['uncompressed_sha256']; originals.append(old_chunk)
            expected_files.pop(old_name); expected_files[old_name + '.gz'] = manifest['files'][old_name + '.gz']; gzip_count += 1
        require(len(originals) == 100, 'Packaged chunk census changed')
        index['chunks'] = originals; scene_original['event_index'] = index
        require(exact(byte_info(encoded(scene_original)), source['files'][scene_name]), 'Packaged geometry/index changed')
        expected_files[scene_name] = artifact_info(folder / scene_name)
        old_record = original['response_record']; response_record = current['response_record']
        delivery = delivery_map(old_record['archive_members'])
        require(set(response_record) == set(old_record) | {'archive_delivery', 'delivery_rewrites'}
                and exact(response_record['archive_delivery'], delivery)
                and all(exact(response_record[key], value) for key, value in old_record.items() if key != 'current_report'),
                'Archive delivery inventory changed')
        response_folder = folder / model / 'response'; rewrites = response_record['delivery_rewrites']
        rewrite_names = {'summary.html'} | ({'original-native/summary.html'} if model == 'KMRC01_candidate' else set())
        require(set(rewrites) == rewrite_names, 'Unexpected rewritten delivery pages')
        for name, bound in delivery.items():
            expected_files.pop(model + '/response/' + name)
            require(not (response_folder / name).exists(), 'Archive-only artifact duplicated')
            response_bytes(response_folder, name, current)
        for name in rewrite_names:
            original_body = response_bytes(response_folder, name, current)
            expected = package_summary(original_body, delivery, original_native=name.startswith('original-native/'))
            require((response_folder / name).read_bytes() == expected
                    and exact(rewrites[name]['delivered'], byte_info(expected)), 'Response delivery page changed')
            expected_files[model + '/response/' + name] = byte_info(expected)
        with zipfile.ZipFile(response_folder / 'ledgers.zip') as archive:
            old_run = read_json_bytes(archive.read('run.json'))
        expected_run = {**old_run, 'web_delivery': {'archive_delivery': delivery, 'delivery_rewrites': rewrites,
            'original_public_report': old_record['current_report'], 'source_full_manifest_sha256': FULL_BUNDLE_MANIFEST}}
        require(exact(read(response_folder / 'run.json'), expected_run)
                and exact(response_record['current_report'], byte_info(encoded(expected_run))), 'Response source/delivery metadata changed')
        expected_files[model + '/response/run.json'] = byte_info(encoded(expected_run))
    require(gzip_count == 200 and packaging['gzip_chunks'] == 200, 'Both complete raw chunk censuses required')
    require(exact(manifest['files'], expected_files), 'Package retained/removed artifact inventory differs')
    measured = sum(info['bytes'] for info in manifest['files'].values())
    require(packaging['payload_bytes'] == measured and packaging['max_payload_file_bytes'] == max(
        info['bytes'] for info in manifest['files'].values())
        and measured + EXISTING_SITE_BYTES + (folder / 'manifest.pending.json' if (folder / 'manifest.pending.json').exists()
                                            else folder / 'manifest.json').stat().st_size < MAX_SITE_BYTES
        and all(info['bytes'] < MAX_WEB_FILE_BYTES for info in manifest['files'].values()),
        'Web package size budget exceeded')
    return source


def package(output=WORK / 'web-bundle'):
    """Lossless delivery derivative of the one registered completed full bundle."""
    frozen = frozen_sources(); source_folder = WORK / 'bundle'
    require(digest(source_folder / 'manifest.json') == FULL_BUNDLE_MANIFEST, 'Unknown full export; do not reseal')
    source = validate_bundle(source_folder, check_local=True)
    output = checked(output, WORK, new=True)
    require(output == WORK / 'web-bundle', 'Use the single assigned web package root')
    require(not (CAMPAIGN / '.supervisor.lock').exists(), 'Scientific supervisor must exit before packaging')
    manifest = read(source_folder / 'manifest.json')
    output.mkdir(parents=True)
    skips = set(); rewrites = {}; scenes = {}
    for model in MODELS:
        record = manifest['models'][model]; response_folder = source_folder / model / 'response'
        selected_name = model + '/selected.json'
        require(gzip.decompress((source_folder / record['selected']).read_bytes())
                == (source_folder / selected_name).read_bytes(), 'Selected gzip differs from original bytes')
        skips.add(selected_name)
        delivery = delivery_map(record['response_record']['archive_members'])
        record['response_record']['archive_delivery'] = delivery
        record['response_record']['delivery_rewrites'] = {}
        for name, bound in delivery.items():
            body = response_bytes(response_folder, name, record)
            require(exact(byte_info(body), artifact_info(response_folder / name)), 'Standalone/archive scientific bytes differ')
            skips.add(model + '/response/' + name)
        for name in ('summary.html', 'original-native/summary.html'):
            if not (response_folder / name).is_file():
                continue
            body = (response_folder / name).read_bytes()
            require(exact(byte_info(body), record['response_record']['archive_members'][name]), 'Original HTML/archive differs')
            new_body = package_summary(body, delivery, original_native=name.startswith('original-native/'))
            record['response_record']['delivery_rewrites'][name] = {'archive': 'ledgers.zip', 'member': name,
                'original': byte_info(body), 'delivered': byte_info(new_body)}
            rewrites[model + '/response/' + name] = new_body
        old_report = record['response_record']['current_report']
        report = read(response_folder / 'run.json')
        report['web_delivery'] = {'archive_delivery': delivery, 'delivery_rewrites': record['response_record']['delivery_rewrites'],
            'original_public_report': old_report, 'source_full_manifest_sha256': FULL_BUNDLE_MANIFEST}
        rewrites[model + '/response/run.json'] = encoded(report)
        record['response_record']['current_report'] = byte_info(encoded(report))
        scene_value = read(source_folder / record['scene'])
        for chunk in scene_value['event_index']['chunks']:
            name = model + '/' + chunk['file']; body = (source_folder / name).read_bytes()
            require(exact(byte_info(body), source['files'][name]), 'Original raw chunk changed')
            zipped = gzip.compress(body, compresslevel=9, mtime=0)
            require(gzip.decompress(zipped) == body, 'Raw chunk compression lost bytes')
            write(output / (name + '.gz'), zipped, public=False); skips.add(name)
            chunk.update({'file': chunk['file'] + '.gz', **byte_info(zipped), 'encoding': 'gzip', 'gzip_mtime': 0,
                          'uncompressed_sha256': byte_info(body)['sha256'], 'uncompressed_bytes': len(body)})
        scenes[record['scene']] = encoded(scene_value)
        record['source_scene_sha256'] = byte_info(scenes[record['scene']])['sha256']
    rewrites.update(scenes)
    for name, info in source['files'].items():
        if name in skips:
            continue
        if name in rewrites:
            write(output / name, rewrites[name])
            continue
        old = checked(source_folder / name, source_folder); new = checked(output / name, output, new=True)
        require(exact(artifact_info(old), info), 'Full export changed while packaging')
        new.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(old, new)
    write(output / 'packaging-source-manifest.json', (source_folder / 'manifest.json').read_bytes())
    manifest.update({'source_records': frozen['source_records'], 'source_freeze_sha256': digest(FROZEN),
        'writer_receipt_sha256': frozen['writer_receipt_sha256'], 'files': {}})
    for path in sorted(output.rglob('*')):
        if path.is_file():
            manifest['files'][path.relative_to(output).as_posix()] = artifact_info(path)
    manifest['packaging'] = {'kind': 'ring_lossless_web_package_v1', 'scientific_recomputation': 0,
        'source_manifest': {'file': 'packaging-source-manifest.json', **artifact_info(source_folder / 'manifest.json')},
        'source_records': source['source_records'], 'gzip_chunks': 200,
        'payload_bytes': sum(info['bytes'] for info in manifest['files'].values()),
        'max_payload_file_bytes': max(info['bytes'] for info in manifest['files'].values()),
        'archive_policy': 'Removed standalone bytes remain exact registered members of the unchanged ledgers.zip. Rewritten HTML is separately delivery-bound; its original stays inside ZIP.'}
    pending = output / 'manifest.pending.json'; write_json(pending, manifest)
    validate_bundle(output, check_local=True, _manifest_name='manifest.pending.json')
    require(exact(frozen, frozen_sources()) and digest(source_folder / 'manifest.json') == FULL_BUNDLE_MANIFEST,
            'Source changed during packaging; preserve incomplete derivative')
    os.rename(pending, output / 'manifest.json')
    return manifest


def assemble(source, target):
    """Copy a checked completed bundle only; no scenes or calculation entry."""
    source = checked(source, ROOT / ".local")
    manifest = validate_bundle(source)
    target = checked(target, ROOT, new=True)
    shutil.copytree(source, target)
    validate_bundle(target)
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("freeze", "scene", "raw", "build", "package", "validate"))
    parser.add_argument("--model", choices=MODELS)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--check-local", action="store_true")
    args = parser.parse_args()
    if args.command == "freeze":
        result = freeze()
    elif args.command == "scene":
        if args.model is None:
            parser.error("scene requires --model")
        result = scene(args.model)
    elif args.command == "raw":
        if args.model is None:
            parser.error("raw requires --model")
        result = raw(args.model)
    elif args.command == "build":
        result = build(args.output or WORK / 'bundle')
    elif args.command == 'package':
        result = package(args.output or WORK / 'web-bundle')
    else:
        result = validate_bundle(args.output or WORK / 'bundle', check_local=args.check_local)
    print(json.dumps({"kind": result["kind"], "status": result.get("status", "frozen"),
                      "models": list(result.get("models", {}))}, allow_nan=False))


if __name__ == "__main__":
    main()
