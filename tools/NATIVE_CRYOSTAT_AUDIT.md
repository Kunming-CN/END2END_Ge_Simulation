# Bounded monolithic native audit

This advanced tool inspects the pinned `LBNLcryostat.tg` with the existing
Geant4 11.3.2 runtime. It imports geometry and samples 1000 native GPS positions;
it generates no primaries/events and runs no particle transport, physics list,
SSD or electronics. The monolithic input stays `candidate_input_only`.
Native structure/source-position completion does not grant an executable adapter,
event mapping, experimental/as-built acceptance or proof of overlap-free geometry.
Keep the existing Windows guide as the setup authority.

From the project root, using the existing Python:

```text
python -B tools/cryostat_native_audit.py check --json
python -B tools/test_cryostat_native_audit.py
python -B tools/cryostat_native_audit.py freeze --json
python -B tools/cryostat_native_audit.py run --json
python -B tools/cryostat_native_audit.py verify --json
python -B tools/cryostat_native_audit.py reinspect --receipt-sha256 EXTERNALLY_RECORDED_SHA256 --json
```

`check` verifies only code-pinned authored expectations, with no private original
reads. `freeze` explicitly creates a source snapshot without building or invoking
native code, copying the exact nine sources to `source-frozen/<relative-ref>`
under the same local root. Ordinary manual contributions do not need private AI writer exits,
autonomy state or a supervisor lock. For this owner-managed round, root creates
the freeze only after both actual writers exit; optional `writer_exits` records
are hash-checked if supplied. A source snapshot is an integrity boundary, not
authorship or physics certification.

The fresh fixed roots are `.local/m11f-cryostat-native-v1/build` and `native`.
The control tool accepts no alternative build/output path and never overwrites
these roots, checkpoints, logs or receipts. Preserve failure evidence and inspect
it with `verify`; failure does not authorize retrying native geometry or radiation.
Symlinks/reparse points and traversal are refused. These are ordinary local path
checks, not a race-resistant sandbox.

`run` first checks all nine recorded original bytes with the existing M11e
checker and verifies pinned Pixi manifest/lock bytes. Every configure/build/version
and native command uses existing Pixi `--locked --no-install`; Windows bridges
through the existing Ubuntu-24.04 WSL distribution. The isolated CMake target does
not change the old transport CMake/backend. Build parallelism is two, native work
is serial. Three code-owned LF shell files are exclusively generated under the
same local root; Bash reads those files with argv, avoiding inline script quoting
across Windows/WSL. Their hashes are bound to command/run records and checked again
by saved verification, including edits accompanied by rehashed metadata.
The tool records source/input/binary hashes, actual versions/compiler/
RNG engine, stage times, command return codes and exact stdout/stderr logs locally.
Sources and inputs are compared again before native execution and afterwards.

Native execution has its own Linux GNU timeout: TERM after 60 seconds, KILL after
five further seconds. Configure/build/version commands have separate 120-second
host bounds; the native bridge also has a separate 120-second host bound to allow
startup overhead. It is not a 60/120-second bound for the whole orchestration.
An exclusive PID marker identifies the owned Linux timeout group; outer bridge
timeout triggers a narrow cleanup attempt after checking the group's command
line against the exact binary/output. Failed cleanup stays unknown and requires
the owner-managed worker inspection before closure. No whole-WSL shutdown or
unrelated process termination occurs.

`verify` reads saved artifacts and recomputes their interpretation without a
subprocess or solver. Partial checkpoints, original errors, return codes, warnings
and timeout receipts remain inspectable. Unknown observations stay null. A native
warning or confinement fallback blocks blanket scoped acceptance. Terminal
statuses distinguish `complete_native_audit`, `completed_with_geometry_failures`,
`completed_with_native_warnings`, import/audit failure and `timed_out_partial`.
The CLI returns success only for scoped acceptance, or metadata/freeze commands.

`reinspect` permits a changed verifier to reinterpret exact historical observations.
It requires the externally recorded original `CONTROL-RUN.json` SHA256, checks the
old freeze and all nine original source snapshots, and verifies raw checkpoints,
logs, binary, generated helpers and consumed inputs. The current native CMake/C++
and expected metadata must still match their original identities. It writes
nothing and returns a separate report with the original failed inspection, new
interpretation and current verifier source hashes. Historical receipts/freezes
remain unchanged; warnings still block blanket acceptance. Hash identity provides
integrity under the supplied external digest, not authorship or physical support.

The public expected metadata contains 22 logical identities/material uses,
23 ancestry/copy identities, 47 authored solid names/types, 15 Boolean constituent
edges, custom material ratios and selected source matrices/settings. It omits
the full upstream TG/MAC text, all raw parameters, full primitive geometry,
private paths and raw reports. Its independent code-owned digest rejects changed
expectations even after external metadata rehashing. All native store solids are
retained: every native ID must be reachable through expected logical identities,
Boolean-origin edges and displaced-to-moved edges. A source origin can produce
separate nonlogical primitive instances; their complete native parameters and
bounds must agree, and each instance must be referenced. Cached logical origins
and Boolean origins remain unique. Every displaced helper must connect a known
Boolean edge to its moved solid by integer IDs; unreferenced or unknown extras
cannot be filtered to force a count. The fixed Geant4 11.3.2
[text geometry builder](https://github.com/Geant4/geant4/blob/v11.3.2/source/persistency/ascii/src/G4tgbVolume.cc)
constructs Boolean constituents recursively and registers finished logical solids
in its manager cache; see the
[cache implementation](https://github.com/Geant4/geant4/blob/v11.3.2/source/persistency/ascii/src/G4tgbVolumeMgr.cc)
(checked 2026-10-02 UTC). The 47 authored definitions are origins, not a forced
native instance count.

Physical object/frame rotations are inverse. Physical `GetFrameTranslation`
is the negative object translation; displaced-solid frame translation is the
full inverse affine translation. The controller checks these distinct native
getter meanings, and independently composes parent-to-global transforms.
`Active -> Holder` is identity rotation, while `Holder -> lab` uses the inverse
object rotation of `r010`; the composed centre is `[37.077,0,0]` mm. See the
official pinned [physical-volume getter source](https://github.com/Geant4/geant4/blob/v11.3.2/source/geometry/management/src/G4VPhysicalVolume.cc)
and [displaced-solid getter source](https://github.com/Geant4/geant4/blob/v11.3.2/source/geometry/solids/Boolean/src/G4DisplacedSolid.cc).

`import.json` is saved before potentially unsafe geometry operations.
`geometry.json` records native bounds, analytic BOX/TUBE primitive volumes,
six selected native Inside probes and 10000 sampled overlap checks per nonworld
placement using seed 26092632. Default stochastic Boolean volumes remain
`null/not_run_stochastic_boolean` and are not an acceptance prerequisite.
Degenerate/invalid diagnostics are retained; unsafe later phases remain incomplete.
Sampled overlap checks cannot prove absence of arbitrarily small overlaps.

`gps.json` records original gamma/59.5 keV metadata and native position getters,
seed 26100161, all 1000 full-precision positions, native Inside and navigator
ancestry/copy identities. No primary or particle is generated. Each position is
independently inverse-transformed into the actual `Active` solid, and must have
strict native interior status and the exact `/lab/Holder/Active` copy chain.
The original envelope radius 1.62 mm/half-length 0.002 mm exceeds `Active` radius
1.61 mm/half-length 0.001 mm intentionally; confinement is preserved. Internal
rejection counts are unavailable and remain null, not zero or a measured efficiency.
Actual `Active` material stays `G4_Au`; the unused `AmO2` definition is not activity.

The agreed checkpoint schema is version 1 with exact common runtime/status/error/
elapsed fields. Partial exception timing keys may be a subset of that checkpoint's
known stage keys; missing later timings remain unknown. Unknown timing keys fail.
Reports retain full unfiltered stores and object/frame
getter values; optional unknowns are explicit nulls. Root's source freeze is:

```json
{"kind":"m11f_source_freeze_v1","source_records":{"relative-source-ref":{"sha256":"...","bytes":123}},"writer_exits":{"control":{"path":".local/m11f-cryostat-native-v1/CONTROL-EXIT.json","sha256":"..."},"native":{"path":".local/m11f-cryostat-native-v1/NATIVE-EXIT.json","sha256":"..."}}}
```

`source_records` contains the exact eight implementation files and `.gitattributes`
(nine refs), including the exact native CMake/C++ LF rules. `writer_exits`
is optional for manual use; each supplied record must identify an exited writer.
Tests use synthetic report dimensions/material values and mocked child commands,
not native acceptance. Their temporary fixtures stay under this round's `.local`.
The actual one native invocation belongs to root after source freeze.
