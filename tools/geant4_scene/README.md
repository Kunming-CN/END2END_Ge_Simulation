# Saved Geant4 geometry and event display

This independent utility reads the completed `cs10000-v2` GDML through
`G4GDMLParser` and generates the actual solids' `G4Polyhedron` vertices, facets,
wireframe edges, placed hierarchy, materials and global transforms. It has no
run manager, physics list, fields, event generation or `/beamOn` command.
The Python exporter checks the native output against the saved geometry report.
No generic cylinder fallback is provided.

From the project root **inside the existing WSL environment**, run:

```sh
bash transport/run.sh cmake -S tools/geant4_scene -B .local/geometry-events-publication/build -G Ninja
bash transport/run.sh cmake --build .local/geometry-events-publication/build --parallel 2
bash transport/run.sh python -B tools/geometry_events.py --check-inputs
bash transport/run.sh python -B tools/geometry_events.py
bash transport/run.sh python -B tools/test_geometry_events.py --bundle
bash transport/run.sh python -B tools/geometry_events.py --validate-bundle
```

The pinned environment is Geant4 11.3.2, remage 1.1.0 / Python 3.13. The exporter
records saved transport versions, source hashes and its runtime. It requires
both terminal 10,000-primary runs, all 17 unchanged computational dependencies,
the original transport/preparation hash chains, and a newly built native utility.
`transport/run.sh` uses the existing locked environment; do not install or upgrade.

Output is exclusively `.local/geometry-events-publication/bundle`. Existing
output, native JSON, and native log files are refused. Failed attempts are
preserved and require deliberate owner/supervisor reconciliation; no automatic
overwrite, cleanup, or retry is performed.

Each model has `scene.json`, 100 JSON files containing 100 events each, and
`originals.zip` with exact geometry GDML, canonical GDML, run macro, scenario,
preparation, geometry report and transport receipts. `manifest.json` binds every
generated file except itself by SHA-256 and records the raw LH5 hashes and
exporter hashes. Original upstream `.tg` sources and raw LH5 are not copied.
Attribution and the upstream repository's absence-of-license observation are
preserved from `transport/cryostat-source.json`; no relicensing is granted.

Rows are copied directly from named `vtx`, `particles`, `tracks`, and every
`stp/*` table, with original column names, values, units, scalar dtypes and
zero-based raw row indices. UID aliases are documented but not counted twice.
All raw columns remain binary64 round-trippable JSON numbers. The full test
compares every scalar to the raw LH5, including float bit patterns. Event
census remains 0..9999, independent of Ge hits. Processes are retained in the
scene index. No world-air path is reconstructed. Track data are creation
vertices/momenta, not continuous paths; only each recorded pre/post STEP chord
is drawn. All times remain raw ns, including delayed daughters.

Serve the bundle with any local static HTTP server, for example:

```sh
cd .local/geometry-events-publication/bundle
python -m http.server 8000 --bind 127.0.0.1
```

Open `http://127.0.0.1:8000/geometry.html`. Once downloaded, no external network
or frontend dependency is needed. Direct `file://` fetching is unsupported.
Browser SHA-256 verification requires HTTPS or localhost HTTP. The viewer has
model/event selectors, previous/next Ge-hit navigation, fitted front/side/default
views, pan/rotate/zoom, visibility toggles, and exact selected-row details.
Only two 100-event chunks are cached; late responses cannot restore stale events.

This exporter does not run the optional central `G4Navigator` ray. Surfaces
of parent solids include daughter regions; transparency is an inspection aid,
not an occupancy or material-thickness analysis. Native curved tessellation is
visualization only. The exact GDML, curved-wall source pose and nominal scenario
are preserved. No detector-response or accuracy claim follows from the display.
