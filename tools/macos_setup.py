"""Prepare the source-bound geometry exporters in the locked macOS environment."""
from __future__ import annotations

import os
from pathlib import Path
import sys
from urllib.request import urlopen


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "transport"))
import angle_exporter_setup
import catalog_exporter_setup
import scenario_source_portable as transport


def acquire_cryostat_sources():
    manifest = transport.load(ROOT / "transport/cryostat-source.json")
    prefix = f"https://raw.githubusercontent.com/{manifest['repository']}/{manifest['commit']}/{manifest['directory']}/"
    target = transport.safe_path(ROOT, manifest["local_cache"])
    target.mkdir(parents=True, exist_ok=True)
    for entry in manifest["files"]:
        output = transport.safe_path(target, entry["name"])
        if not output.exists():
            download = transport.safe_path(target, entry["name"] + ".download")
            with download.open("xb") as stream, urlopen(prefix + entry["name"], timeout=45) as response:
                stream.write(response.read(entry["bytes"] + 1))
            verify_source(download, entry)
            os.link(download, output)
            download.unlink()
        verify_source(output, entry)


def verify_source(path, entry):
    transport.require(path.is_file() and path.stat().st_size == entry["bytes"]
                      and transport.digest(path) == entry["sha256"], f"Cryostat source differs from the pinned bytes: {path}")


def main():
    runtime = transport.runtime_snapshot()
    transport.require(runtime.get("platform") in ("osx-arm64", "osx-64"), "Run this setup through Setup.command on macOS")
    print("Verified remage 1.1.0 and Geant4 11.3.2 in the macOS lock.", flush=True)
    print("Acquiring the pinned cryostat source files.", flush=True)
    acquire_cryostat_sources()
    for build in (transport.build_exporter, catalog_exporter_setup.build, angle_exporter_setup.build):
        print(f"Building {build.__module__}.", flush=True)
        receipt = build(str(ROOT))
        print(f"Verified {receipt['exporter']['ref']}.", flush=True)


if __name__ == "__main__":
    main()
