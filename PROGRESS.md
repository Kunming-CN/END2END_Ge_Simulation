# Current project state and next steps

Updated: 2026-09-30. Current status below supersedes historical milestone notes.
The 1M/model Geant4 AND native SSD/readout campaign is COMPLETE. No science worker is active.
Response publication: `11dd951`; interactive geometry/navigation publication: `99f5c1b`.
Do not restart any completed simulation, analyzer or reviewer because the chat stream timed out.

## Current handoff: M4b saved-charge electronics replay

`Run.cmd replay-readout -Name SOURCE -ReplayName NEW [-Detector AK02|SAP22|both]
[-ElectronicsProfile PATH] [-DryRun] [-Json]` creates a separate, checked synthetic
electronics derivative. No Geant4, field solve or SSD charge transport is called.
Dry-run checks stored support/configuration without Julia or output reservation.
The current M4a observer still reports conservative runtime/replay eligibility;
the separate M4b command performs its own actual runtime and completion checks.
See `tools/CHARGE_REUSE.md` for commands, limits and receipt/output locations.

Actual normal-host acceptance used the existing Julia1.13.0/JSON1.9.0 installation
and unchanged readout modules. Same settings reproduced original calibration,
all scalar records and saved traces; identities/clocks/ADC/selection were exact,
with predeclared analog tolerances. A threshold-only0.05V derivative accepted
213/450 and rejected220/325 while analog signals/calibration/ADC stayed unchanged.
Both retained500 primaries,496 zeros,4 groups,20008 charge samples and step-limit
flags26/88/35/59. Full stored coverage is NOT complete physical charge collection.
Successful derivatives are `.local/replays/m4b-coordinator-host-v2-same` and
`m4b-coordinator-host-v2-threshold`; the earlier failed derivative remains evidence.

The driver retains the source read-only exclusive lease, records exact inputs,
validates loaded runtime/profile/census/worker output, and publishes an atomic
outer receipt only after final checks. Repeat output names never overwrite.
Native-failure nulls and signed negative input have explicit software fixtures;
actual failed-native and SAP22 numerical replay were not newly certified here.
M5 per-group recovery and general large/serialized replay remain undelivered.

Final evidence:27 current replay workflow tests,88 checker tests,21 actual Julia
parser/runtime assertions,7 actual independent CLI commands with2 successful
numerical derivatives,2 final valid dry-runs and current read-only revalidation
of both immutable derivatives. All1799 protected files remain exact in hash,
size and mtime, including the61-file source run. No original science was rerun.

The author left a frozen handoff but stalled before its final response; only that
idle author tree was closed, and exit1 remains explicitly coordinator-induced.
Sandbox Julia path refusal was not a broken host installation. The new worker's
mixed-type metadata and quoted-numeric CSV defects were corrected and tested on
the host. A non-grid gate-verifier defect was independently reproduced/fixed.
Physics review subsequently found missing two-sample gate preflight: invalid
windows now fail before Julia/allocation. Explicit empty profiles cannot silently
fall back. An AST comparison proves those last two guards are the only execution
code delta after the successful numerical runs; original receipts stay unchanged.
Later tests hit an audit-helper traversal error and pvpython's empty-argument
startup bug; scoped test-only corrections retained their criteria and failures.
No permission, installation, global PATH/package/default-model change was made.

Two scoped reviewers and a NEW independent third-party detail/direction reviewer
used GPT-6.1-Sol Ultra, confirmed by actual session metadata; their initial
reports and cross-closure are in `.local/charge-replay-v1/`. The third-party
assessment supports the goal and shared-backend approach. Optional idea for owner
discussion: a concise human result summary with synthetic-model label, calibration
slope and receipt path. It is not implemented or a reason to build the GUI early.
Complete test/source/preservation/Git closure: `.local/charge-replay-v1/COMPLETE.json`.

NEXT M5: bounded atomic per-group charge/readout checkpoints for NEW small runs;
then M6 optional existing-LH5/official API pilot and M7 physically checked adapters.
M3 preamp/ORTEC/noise/optimal-resolution work and M8/M9 novice/no-code trials stay
DEFERRED. Fresh-machine tests wait for a second computer; no installation trials
on this working PC. M10/M11 remain future mouse-interface/extension work using
the same backend. Maintain one project and tracked local/GitHub source/config
parity; private data, machine-specific paths and evidence remain local.

## Retained bounded preamp waveform audit

M3 equation/saved-waveform audit is complete; see `tools/PREAMP_AUDIT.md`.
The owner's screenshot is AK02 event2 from the older100-primary/model mono662
pipeline, NOT the million-native campaign. All49 charge samples through96ns are
retained in the600-point display; its negative preamp minimum is-13.465970mV at94ns.
The saved readout ends at10096ns with-11.024563mV. Cf0.6pF and feedback50us explain
this: the appended10us is20 shaping constants, only0.2 feedback constants, leaving
81.873% of the post-charge preamp amplitude. No display sign inversion, charge-unit
error or decay-exponent error was found in the bounded inspected path.

31 numerical assertions using the unchanged actual Readout module passed,
including analytic injection/finite-current checks, scaling/sign/grid/charge
balance and comparison to this saved event. Complete49-sample charge support was
used, not generic reconstruction from decimated traces or a spectrum. The older
producer and current tested code hashes remain distinct; no receipt was rebased.
Evidence: `.local/preamp-audit-v1/COMPLETE.json`. Two original Astra reviewers used
XHigh for physics and High for data/display, then exchanged actual findings.

This event's stopped_without_contact flag remains. Zero current after the saved
endpoint is not proof of physical collection completion. Laboratory inventory is
partly documented (LBNL Square/BF862, nominal0.6pF, ORTEC671/927, DSOX3034A), but
actual acquisition node/polarity/gain/coupling/reset details remain unverified.
No claim of experimental waveform agreement or generic replay eligibility follows.

Remaining M3 work is deferred by the owner; active M4 priorities are above.
Original audit evidence and unknown hardware settings remain unchanged.

## Retained reciprocal current Geant4 readers

M2 now has maintained saved-data readers at `viewers/geant4-assembly.html` and
`viewers/ge-positive.html`, with visible reciprocal buttons and actual model/
primary selection continuity. Overlay group IDs survive the round trip where
represented; assembly labels them return-navigation context, not rendered groups.
Zero/absent/filtered primaries or missing groups are not replaced by an arbitrary
highlight. Malformed requests fail visibly; late successes and failures cannot
replace a newer selection. Original radiation records are not full trajectories.

Maintained detector/result/spectrum links use these current routes. Original
`examples/cs137-10k-geometry/geometry.html` and `cs137-10k-hits/hit_event_view.html`
remain byte-exact archives with historical navigation. Their original templates,
manifest, geometry and event payloads were not rewritten. Population labels stay
10,000 initial decays/model, with121 AK02/115 SAP22 Ge-positive primaries, not1M.
The new display manifest separately binds original data and adapter/readers.

Astra High implemented the adapter; the original physics reviewer used High,
while integrity used Astra XHigh. The XHigh provenance finding was independently
reproduced: unknown source hashes could skip deterministic HTML reconstruction.
The corrected validator rejects this; a prior display is readable only through
an explicit entire-manifest pin, not self-declared source compatibility. New
exports require current source hashes. Tests cover modified/rehashed HTML and
unknown sources, including tampering with the trusted-old-manifest path.

Final component evidence: 104 distinct Python tests pass across
the relevant suites, plus query/actual-script checks and 26 real-browser
checks across two host harnesses. The failed contact-test aggregate is retained
and reconciled with its separately passing unchanged-source retry.

Terminal test, production browser, preservation, Git and live-deployment evidence
is in `.local/viewer-navigation-v1/COMPLETE.json`; retain its failed attempts too.
Browser checks use dedicated host Edge profiles over localhost with no external
page-service requests, plus390/834/desktop emulation. They are not native iPad/
Safari or direct-file-fetch certification. See `tools/VIEWER_NAVIGATION.md`.

All347 protected local hashes, sizes and this round's observed mtimes are unchanged;
all1445 prior public paths remain. The earlier M1 difference in24 empty-file mtimes
remains historical evidence, with unknown cause and no timestamp repair. M1's22
static/dynamic spectrum specifications remain exact; only relevant links changed.

Retained failures: sandbox Edge failed before page load; host execution worked
without disabling browser security. The first host harness deadlocked while
awaiting a deliberately deferred selection Promise; the corrected test uses void
and retains its assertions. An unchanged contact-test fixture hit Windows rename
access denied, rolled back, and passed one separately recorded retry. The original
failed aggregate is not relabelled passed. The first candidate build/check passed;
a second build/check was required only for the reproduced provenance correction.
No radiation, field, carrier transport or electronics calculation was repeated.

M1 is complete at `f2bc220`: solid step spectra, independent truth/accepted-ADC
checkboxes and Log/Linear. Recovery of its failed HTTPS wrapper reused the existing
Node-TLS verifier and checked455 online artifacts; `.local/display-repair-v2/COMPLETE.json`
is now terminal. Never repeat that completed development merely to recover a reply.
The sparse AK02 spectrum retains genuine quantization gaps: the frozen synthetic
ADC spacing is1.2455808018023982keV for1keV bins. Do not smooth or rebin old results.

M3 numerical/saved-example audit is recorded above. Remaining M3 presentation and
hardware-response work is deferred by the owner, not a prerequisite for M4.

Then M4 full signed-charge eligibility and separately calibrated electronics-only
derivatives; M5 per-group charge/readout commits for NEW small runs; M6 tiny
optional existing-LH5/official API pilot after actual compatibility checks; M7
physically checked detector adapters and actual fresh-machine reproduction.
Keep the laboratory remage/SSD workflow, not a wholesale simflow rewrite.
The older M2 Astra-only policy is superseded by the current Sol6.1 Ultra policy
in AGENTS.md. Earlier launch receipts stay historical; no paid API or reset credits.
M3 UI/laboratory-response, general replay/group-recovery/new-detector/cold-machine acceptance remains pending.

Historical raw-viewer suites remain source-incompatible; this round used
sealed saved-bundle checks without rebasing those older producer bindings.

## Retained completed-child metadata recovery (2e73937)

`Run.cmd recover -Name NAME [-DryRun] [-Json]` and menu **R** now reconcile a
completed final guarded native child whose campaign-parent update was interrupted.
This is metadata-only: no Julia/WSL lookup, runtime readiness probe, simulation,
calibration, per-group resume or electronics replay. See `tools/RECOVERY.md`.

New campaigns durably save an independently bound executable/argument, input,
profile/configuration, source, detector and census intent BEFORE native launch.
Recovery requires the existing exclusive run lock and verified complete child.
Legacy orphans, missing/partial children, pre-guard receipts, incompatible sources,
rehashed settings mismatches and missing/held locks remain blocked. Old receipts
are never rebased. Current-code incompatibility does not imply corrupt science.

Exact before/after parent bytes, immutable PREPARED evidence, atomic replacement
and an additive COMMITTED marker support checked reentry. Conflicting markers
fail before mutation. Complete parents are read-only no-ops; a partial parent with
no new completed child returns a read-only refusal. An unfinished second detector
remains nonterminal and is never launched by recovery. Original child files,
stage history, errors, timing, native failures, nulls and zero primaries remain intact.

Terminal evidence: 20 recovery + 19 electronics execution + 23 settings + 22
saved-run validation + 6 existing native-launcher tests passed, plus PowerShell
launcher checks. These use explicit mock children/process-death fixtures, not
new physics acceptance. Independent coordinator checks passed 15 CLI commands,
conflicting-marker rejection before writes and a read-only historical-run refusal.
All 347 protected files retain SHA-256, size and mtime. Original science was not
rerun. Evidence, failed tests and the original reviewer threads' plan/code checks
are in `.local/recovery-plan-v1/`; its COMPLETE.json records final release closure.
Only the marked saved-run test fixture's relocated mock-executable path changed
after the first frozen candidate; production checks were not weakened.

Retained electronics capability: saved simple/advanced bundles are copied with
lineage/default/source bytes and passed as the actual guarded-child profile.
Inspect/resume use recorded copies, not new caller settings. A guarded10k request
still needs a clean guarded500 pilot with a positive group for each requested model;
old unguarded pilots do not authorize it. See `tools/ELECTRONICS_SETTINGS.md`.
The prior uninstrumented custom AK02 500-decay acceptance remains 4 positive/accepted
groups, 0 rejects and 0 native failures, at `.local/runs/custom-electronics-500-ak02-v1`.
It is bounded existing-machine evidence, not all-detector or fresh-machine acceptance.
Its original execution/review records remain in `.local/electronics-execution-v1/`.

After M2 reciprocal navigation and M3 preamp audit above: establish complete signed-charge waveform eligibility, then electronics-only
replay where saved inputs support it. General small-run per-group recovery and
physically checked additional LBNL adapters remain separate unfinished milestones.
Partial native-stage recovery, broad SAP22/new-detector positive acceptance and
fresh-machine reproduction are NOT completed by this metadata feature.
Never restart completed science, rebase old receipts or consume reset credits after
chat interruptions. Read COMPLETE.json and actual processes before continuation.

## Retained validated capabilities

- Scientific outputs: 23,693 groups = 21,672 accepted + 1,613 readout rejects + 408 unavailable native responses.
- Failures: 403 boundary-stall cases and 5 SAP22 contact-domain cases. Truth remains intact; unknown response is never zero-filled.
- Final scalar audit is `.local/native-final-analysis-v3`; final report is `.local/native-final-report-v2`. Reuse them, not v1/v2 failed experiments.
- Public final response: `examples/cs137-1m-response/report.html`. All 17 detector pages now have geometry/gallery/technical routes; geometry viewers preserve all 66 contacts, including GeGI's 34.
- Full first-visitor route implemented: three action-first homepage entries with saved previews, concise detector overviews and deeper gallery/technical pages, explicit earlier-10k labels, legacy links/fragments, and one authoritative Windows setup guide. README remains an entry route, not a competing installation manual.
- Low-code v1 is implemented: `Run.cmd` -> check/setup/run/resume/open/status, with a data-only LBNL scenario, pinned preflight, guarded native entry and stage-level reuse.
- Native artifacts/input/source/profile/receipt bindings are verified before reuse. A per-run exclusive lock and atomic run receipt protect ordinary concurrent starts/interruption.
- The prepared seed must match the campaign seed; the deliberate mismatch fixture rejects before transport. Scenario references remain constrained to reviewed canonical files.
- The guarded 20-decay smoke is an installation/zero-census test (zero positive groups), NOT a validation of nonzero pulse response or an independent clean-machine reproduction.
- New bounded acceptance: 8 saved positive groups (1000 retained primaries) pass 64 assertions after scoped review hardening, through the guarded main argument path with explicit test-only field-cache injection. All 149 protected files retain SHA-256/size/mtime. This is NOT uninstrumented Run.cmd acceptance.
- Isolated same-machine source clone correctly rejects missing prerequisites (check exit 2; dry-run nonzero) without installing or calculating. Pinned transport version checks now forbid implicit installation. See tools/LAUNCHER_ACCEPTANCE.md.
- Incomplete small-run native stages are preserved and require inspection; this launcher does NOT implement the million-campaign per-group resume. Do not advertise that capability.
- Current evidence: `.local/all-detector-pages-v1/`, including `outsider-audit/`. A fresh strict reviewer raised seven onboarding/maintenance issues; both original reviewers discussed them and all seven were addressed. Final review/publication receipts are retained there; prior launcher acceptance remains `.local/launcher-acceptance-v1/`.
- `Open_Workspace.cmd` opens a guarded local-only results/file index: final reports first, historical evidence collapsed, original science paths retained. The loose presentation move has an exact hash/mtime/reverse journal.
- Core regression: seven Julia suites and 37 transport/handoff tests passed without Geant4 generation or field solving. All-model browser, link/fragment, repeat-generation, original-root and same-machine 22-file clone checks are separate evidence, not cold-machine reproduction.
- Final closure: independent outsider initial audit and re-audit, original site-UX r4 and workflow r5 (including a corrected -NoOpen wrapper). Release browser checks bind build `b5b1c9a76ac213dc7ee8a670fd867c2f5f6e04b3912b5b0a8fae45f7a05dd889`; 89 pages/2716 links and all 17 viewers pass. Exact commit/live deployment receipt is `.local/all-detector-pages-v1/COMPLETE.json`.
- Spectrum presentation: current routes use `spectra/million-truth.html`, `spectra/million-response.html`, `spectra/cs137-10k.html` and `spectra/pipeline.html`. All 20 current panels including the homepage use default true-log step histograms with Linear/Log controls. Pipeline scale persists across model/event selection; original 24-bin grouping is checked unchanged.
- Original report URLs are intentionally retained as archived presentations with unchanged publication hashes, scientific downloads and signed waveforms. Current generated navigation and the refreshed local workspace target the new display views. No radiation, field, native-response, electronics or completed analysis run was repeated.
- Spectrum acceptance: 19 dedicated tests plus site/hierarchy/model/contact suites; actual browser controls, count/path invariance, two pipeline states, unchanged waveform DOM, keyboard, offline and no-JavaScript log fallback. Mobile390/tablet834/desktop views checked, not a physical iPad/Safari certification.
- Preservation: all1439 previous public files retained; original report/data/model/media bundles unchanged. All173 protected local files retain hashes, byte counts and modification times. Evidence: `.local/spectrum-display-v1/`; see `tools/SPECTRUM_DISPLAY.md` for semantics and exact current/original distinction.
- The same site-UX and workflow threads completed three scoped spectrum review rounds and closed the tested release. Rendering-source ownership and archived/current URL mapping are documented in `tools/SPECTRUM_DISPLAY.md`.
- Saved-run validation now has one shared PowerShell contract: complete response artifact/source inventories, byte sizes, independent native/profile settings, stream/prepared bindings and parent-child census checks. Existing parent-bound children must validate before any resumed receipt rewrite; missing children never authorize a replacement calculation.
- New `Run.cmd inspect -Name RUN_NAME [-Json]` and `resume -Name RUN_NAME -DryRun` read saved files without Julia/WSL, new locks, output writes or scientific execution. Exit 0 means terminal saved-state compatibility only; exit 2 reports blockers. `terminal_compatible` is not runtime readiness or permission to execute. Current-source mismatch does not imply data corruption or a need to rerun/edit original receipts.
- Inspector reports phase states, expected native seed, source compatibility and snapshot stability. Linked descendants, held/inaccessible/missing locks, missing parent hashes, partial children and contradictory counts block reuse. `open` remains a separate action that may regenerate its local index.
- Evidence `.local/lowcode-inspect-v1/`: 22 targeted file/command tests passed, including saved positive/zero and explicit legacy-pilot checks without recalculation; 24-file same-machine source clone passed negative preflight/missing-run inspection. All 272 protected originals retain hashes/sizes/mtime. The initial failed path-handling test and source snapshots remain preserved. Both original reviewer threads closed three scoped rounds.

## Preserved history

The complete pre-cleanup development log is preserved [at its immutable Git commit](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/0d462ade58edcd75aa25aed18056e420967239c8/PROGRESS.md).
An exact local backup is `.local/maintenance-context/PROGRESS-before.md`.
Raw runs, source hashes, review exchanges, failures and release tags remain intact.
Consult only the relevant historical section when needed; do not reread the whole log.

## Owner additions: all-model viewing, detector replacement, local organization

The owner explicitly requested all catalog detectors, not just AK02/SAP22, to have
simple browser drag/rotate geometry. This is a presentation capability, not proof
that every model fits the current fixed LBNL cryostat or has a full-chain adapter.
Local detector replacement must ultimately propagate the selected model through
assembly placement, Geant4 deposits, SSD fields/charge, contacts and electronics,
with saved configuration and no silent physical resizing. AK02/SAP22 selection
already uses that shared implemented chain; the remaining catalog models require
explicit placement/geometry/readout integration and remain visible but disabled
for LBNL execution. Do not mark universal end-to-end replacement complete merely
because the viewer or capability table lists 17 models.

Project-local file organization is also in scope: a categorized local workspace
entry and private reference-document folder, with original scientific paths,
archives, checkpoints, model sources and review history retained. Only a checked,
reversible move of the loose presentation is authorized by this round; no blanket
cleanup of .local, no unrelated computer changes and no implicit resume/run.

## Goal and constraints

Deliver a maintainable local Geant4/remage -> SSD -> preamp -> analog shaping ->
peak ADC -> reconstructed-energy workflow with clear offline/web examples.
AK02 (Anupama ICPC2, Li contact) is primary; SAP22 is a non-Li cross-check, not a
matched geometry. GeGI development is deferred until its cryostat model is available.
Keep original 78 K model snapshots; runs use an explicit 77 K override and canonical
+500 V / +700 V biases. Measured spectra exist; original measured pulse waveforms do not.
Use the owner's computer for all implementation/calculation. Preserve originals,
signed charge, event identities, zeros, deposition times and all numerical flags.
Never use banked/reset credits, switch to separately billed APIs, force-push or
silently replace measured/model parameters. Default Codex: Astra High; XHigh only
for a bounded difficult review when useful. No background schedule changes implied.

## Verified deliverables
- Website: 17 detector galleries, original YAML/include downloads, two-contact views.
- Pinned Julia/SSD CPU and optional CUDA examples; Windows plus WSL Geant4/remage.
- Full 100-primary/model AK02/SAP22 engineering pipeline and compact offline explorer.
- Bounded presets and a one-thread option; default two threads, serial detector jobs.
- Native Li example: four selected AK02 primaries 0/2/41/78, 14 legacy/native cases,
  native diffusion on and zero-field termination off, independent E/N parcels,
  original deposition delays and one shared injection calibration through readout.
- Native example repeats exactly; legacy cases remain unchanged. The timed final
  solve/replay/readout/report interval was 67.405 s, excluding initial module startup.
- Opt-in signed-input positive-peak policy and finite peak gates are implemented;
  signed waveforms and default legacy behavior remain unchanged. Both14-case repeats
  matched original charge CSVs exactly. Current tests:25,804 legacy,49 policy,
  99 complete-identity/mutation assertions; independent physics/integrity closure approved.
  Local evidence: `.local/peak-native-delivery/verified-item1.md`.
- Reusable native AK02/SAP22 entry and schema-2 electronics profiles now pass six
  Julia suites. The prepared-stream `count` shadowing bug was reproduced, fixed
  and covered by a real prepared-input fixture (39 stream assertions).
- Native 100-primary comparisons completed: AK02 54 groups / 53 accepted; SAP22
  55 / 55. All 200 primaries and every endpoint remain. Source history is preserved
  across the subsequent stream-only correction; old receipts were not rebased.
- Actual Cs137 nominal cryostat pilot completed: **500 decays per detector**,
  4 positive groups / 4 accepted each, with all zero-hit decays retained. Both
  producer/consumer dependencies, raw files and 16 response artifacts/model pass
  the independent full-pilot guard. Evidence: `.local/peak-native-delivery/cs500-v3`.
- **The strict 10k run stopped at AK02 event 8432**, not a completed result.
  Output: `.local/peak-native-delivery/cs10000-v1`; check its run.json and actual
  workers before changes. The strict helper rejected a noncontact exterior endpoint;
  a bounded diagnostic also encountered invalid waveform support. Do not relax
  those checks or invent an ADC value. Explicit failure-ledger mode is now tested
  (105 native-entry assertions, 43 exporter cases) and reciprocally reviewed.
  A new clean 500/model pilot, cs500-v4, has identical successful pulse numerics,
  fields, calibration and full example charge CSVs to cs500-v3.
- **10k initial Cs137 decays/model finished on 2026-09-26 at 17:37:16 CDT** in
  `.local/peak-native-delivery/cs10000-v2`; status `completed_with_native_failures`.
  AK02: 9879 zero-Ge decays, 121 groups = 107 accepted + 13 readout rejects + 1
  native failure. SAP22: 9885 zero-Ge decays, 115 groups = 113 accepted + 1 readout
  reject + 1 native failure. Both full primary censuses remain; failures are unknown
  responses, not fabricated zero charge. All 10 stages exited 0; elapsed 910.709 s.
  Recovery verified all 17 recorded source hashes and the existing artifact/ledger
  exporter. `comparison.html` and `comparison.json` now exist in that run root.
  No new agents or physics calculations were launched during recovery.

- Saved-results public bundle is built at `docs/examples/cs137-10k/`: 28 files,
  about 50.9 MB, with all 18 original response files per detector preserved in
  lossless ZIPs. Raw LH5/field caches/upstream geometry stay local. Publication
  rechecked all 17 recorded computational dependencies; none changed.
- Publication-only tests pass: 8 archive/adapter/live tests, 44 report cases,
  19 site tests and 27 contact-display tests. Two bounded reviewers and reciprocal
  closure found no remaining publication blocker after adding complete online
  ZIP checks. Quote-style and CRLF compatibility issues were caught before swap
  and regression-tested. No simulation or native-physics review was repeated.
- The prior 1,067-file website retained 1,064 files byte-for-byte; only its home
  and two detector landing pages gained links. Local build: 1,095 files / 1,754
  checked links. Evidence: `.local/campaign-publication/audit.json`.
- Publication commit **ed733ef** is pushed. GitHub Pages verification passed for
  **108 remote files**, including EVERY new campaign artifact and both ZIPs.
  Live build ID: `292b389cd710b564dcebf33b2637bf5ba010560366e114cc12156c802d999be2`.
  Desktop comparison/trace previews were inspected; exact narrow mobile layout
  is not claimed validated. No original simulation records were changed.

## Exact Geant4 geometry and recorded events

The source is centered above the crystal at global (0,37.073,0.290) mm,
but above the CURVED cylindrical Al wall on +y, not the flat axial end face.
Source-to-highest-Ge distances are 26.223/25.623 mm for AK02/SAP22. This is a
nominal pose, not an as-built lid survey. Raw Ge-hit fractions 1.21%/1.15%
are consistent in order of magnitude with an explicitly approximate 1.06%/0.95%
solid-angle/attenuation check; not measured efficiency validation.

The saved-data bundle is published at docs/examples/cs137-10k-geometry/.
Native G4GDMLParser/G4Polyhedron exports all 20 actual placed volumes per model.
Exact GDML/macros/scenario/preparation receipts are in each model originals.zip.
All 10,000 primary IDs/model and ALL recorded rows are present: 472,658/478,172
scored steps and 85,858/86,276 track creation records. World-air paths were not
scored; STEP chords and creation vertices are not complete trajectories, SSD
carrier drifts or all-event readout waveforms. No missing connectors are invented.

All 13 geometry tests, including a full raw-LH5 scalar-by-scalar comparison,
5 publication tests, 4 efficiency-audit tests and 19 site tests passed. Actual
browser tests covered both models, zero/last primary, stale selection handling
and 390-pixel mobile width. Desktop/mobile views inspected. All 17 original
computational hashes remain unchanged. No radiation/SSD/readout was rerun.
An early derivative export correctly refused source mutation while its writer
was finishing; preserved under bundle-pre-freeze. Final export ran after the
writer exited and source hashes froze. Evidence: .local/geometry-events-publication/.
Build ID: 01ad76ec12526a266a78405f172151bdf8172b1c0053f68726333f8fa5360b61.
Published commit: **8cf3c7a**. Online SHA-256 verification passed for **316 files**,
including EVERY geometry/event chunk and both exact-input ZIPs. Both focused
reviewers closed their findings using the final export/test/browser receipts.
Open [the geometry and all-event viewer](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-10k-geometry/geometry.html).

Entry points: [library](https://kunming-cn.github.io/END2END_Ge_Simulation/),
[full engineering example](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/pipeline.html),
[native Li to readout](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/native-li/comparison.html),
[10k Cs137 comparison and response ledgers](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-10k/comparison.html),
[accuracy diagnostics](https://kunming-cn.github.io/END2END_Ge_Simulation/lithium/lithium.html).
Local native example: `.local/native-li-example/comparison.html`.
Important source: `simulation/native_li_example.jl`, `simulation/readout.jl`,
`simulation/replay.jl`, `tools/pipeline_demo.py`; see module READMEs for commands.

## Current independent campaign:1M initial decays per detector

Standalone Geant4 transport COMPLETED at `.local/cs137-1m` on 2026-09-27
01:56:46 UTC. COMPLETE.json and launcher exit=0 agree: 200 batches, 2,000,000
initial decays. No worker remains. Do not resume or relaunch completed transport.
Target: AK02 and SAP22 each1,000,000 uncollimated Cs137 decays in the SAME geometry,
100 chunks of10,000 per detector, serial models. No SSD or readout is running.
Final Ge-positive counts: AK02 12,420 and SAP22 11,272; no SSD/ADC for this1M run.
`progress.html` refreshes locally; Monitor.cmd, Resume.cmd and Pause-After-Chunk.cmd
are in the campaign folder. Closing the monitor does not stop computation. Keep the
computer powered and awake; power settings are unchanged. DONE chunks are verified
and skipped on resume. Only an unfinished transport chunk may need recomputation.
Raw successful output is losslessly archived; compact HDF5 retains all-primary
scalars and original Ge-related records. No million-event browser JSON is generated.
Driver/launch implementation is committed as **d532fe6**; settings/data stay frozen.

Validation:11 storage/recovery/lock tests, bit-exact oldAK02 compaction, real1000/model
pilot paused at500 and resumed with firstDONE hash AND modification time unchanged.
Current launcher also completed a10/model smoke; owner-finalizer synthetic test passed.
The initial transport coding agent was stopped after a recorded WebSocket idle timeout;
no retry campaign was opened. Current driver was completed directly through Desktop Commander.

New saved-data viewer at `docs/examples/cs137-10k-hits/hit_event_view.html` overlays all
121/115 Ge-positive primaries from the OLD10k runs. Its2.46MB bundle preserves selected
records losslessly. AK02 example IDs:9378 compact/full,698 one observedCompton/full,
9644 two observedCompton/full,8422 partial. All are explicitly candidates, not calibrated
PSD labels. SAP22 one-site example is a31.8keV photon, not the662keV line.
31 viewer tests,7 publication tests and19 site tests passed. The category-during-model-load
race found by integrity review was fixed and regression-tested; both focused reviewers
closed findings reciprocally. Actual desktop/mobile browser tests passed, including
all categories and390px width. No original radiation/native/readout data were rewritten.

Publication **86e5072** is pushed; GitHub Pages SHA-256 verification passed for
323 files including all new overlay assets. Build ID:
a8a7999961e530ed371bc289b9e59521db00f2b9002e960b1afd6a7148648937
Evidence: .local/million-transport-dev/audit.json and live-verification.log.

Next: use the completed saved-data analysis below; transport must not rerun.
Do not restart old10k, finished chunks or native Li research while waiting. The worker
reconciles its matching private supervisor state on normal completion/pause/failure.
If the machine interrupts, verify process absence and resume, not prepare again.

## Completed million-decay preservation and postprocessing (2026-09-27)

Full200-archive compressed/decompressed SHA-256 and byte-count audit passed;
all compact HDF5 datasets, global ranges, counts and Ge energy sums checked.
No original scientific files were changed or deleted. Preserve `.local/cs137-1m/`
per tools/DATA_RETENTION.md; it is permanent data, not disposable cache.
Exact input/source/checkpoint snapshot and audit: `.local/million-analysis/preservation/`.
Saved-data analysis completed ONCE,86s including verification, with23 tests passed.
AK02:12,420 positive groups,806 line full-energy candidates,150 unknown groups.
SAP22:11,272 positive primaries /11,273 groups,531 line full candidates,166 unknown.
Unknown classification remains in the ledgers; it is not failed radiation transport.
Outputs: `.local/million-analysis/analysis-results/`; see tools/MILLION_RESULTS.md.
These are deposition truth, not ADC spectra. No native-response batch was launched.
Publication dd3117f is pushed; 331 remote files were downloaded/hash-verified,
including every new1M report/data file. New page: examples/cs137-1m/report.html.
Four audit,23 analysis,3 public semantic and19 site tests passed; two bounded
reviewers completed reciprocal closure. Desktop report preview inspected.
Final postprocessing audit rechecked1,400 protected files and20 computational
source hashes: zero original changes/deletions. Evidence: .local/million-analysis/.

## Completed selected HDF5-to-native pilot (2026-09-27)

The bridge is implemented; do not rebuild it or rerun the full pilot just to recover
context. See tools/NATIVE_BRIDGE_RESULTS.md and .local/native-bridge-pilot/.
Final contracts-v3 feed pilot-v2:23 selected million primaries (2zeros),22positive
groups,22accepted ADC results; two additional old diagnostic primaries are separate.
SAP22 primary965630 retains two groups. Compute/export interval133.134s; OS exit0
independently observed. Existing fields/calibration/profile match old10k exactly.
AK02 all9new groups have caps; SAP22 one of13groups has stopped-without-contact
flags. AK02 primary3950 has661.657keV deposited but only59.169keV induced and
47.955keV ADC; retain this concrete low-response case rather than assuming validity.
Old AK8432 fails as before. Old SAP8413 succeeds in the mixed pilot but FAILS in
all3fresh-process isolated repeats of that control with the same saved inputs/seeds
and field fingerprints. Cross-context reproducibility remains unresolved, not fixed.
No full-million native processing is launched. Do not erase or silently relabel
old failures. Exact charge/endpoint/scalar/trace outputs and failed pilot-v1 remain.
Tests:13Python bridge,87Julia assertions,3rehashed metadata/units,4output-ledger
mutation,4renderer. Output-order bug fixed without changing frozen solver; true
process exit verified independently of invalid temporary null-code receipt.
Report-v2/comparison.html is a LOCAL selected waveform report; source/result notes
are versioned. Original public million report remains deposition truth only.
Preservation-after.json confirms1400campaign files,20original sources and9saved
analysis artifacts unchanged. No Geant4 or million-analysis rerun occurred.

Next bounded work: isolate SAP22 control execution-context dependence and assess
AK02 primary3950/cap impact, using existing records and few targeted calls. Then
build resumable full native response using cached fields and saved HDF5. This is
not a new global Li/PDE gate or permission to repeat completed source simulation.

## Native boundary correction and production checkpoint stage (2026-09-27)

SAP22 old8413 context dependence is now explained by a CONFIRMED SSD0.11.8
unwritten path row: row2694/parcel1/step23 returns either arbitrary sentinel.
New opt-in native_boundary_guard.jl throws a typed boundary failure before signal
creation; it does not invent a point/charge or repair physical surface transport.
Old mixed-pilot SAP8413 finite response is unreliable historical evidence, preserved.
26 guard assertions pass: same failure before/after perturbation, good control exact.
AK023950 paired10/20us test matches1600 carrier path/time prefixes; charge delta
1.91e-12keV, ADC unchanged. Conditional remaining bound0.005836keV.2594 has1216
prefixes and0.014502keV bound. Large low response is not the tested10us cap loss.
Do not force charge to truth; default lifetime/contact model remains uncalibrated.
Both existing agents exchanged findings through several bounded rounds and closed
the guard/world-age, checkpoint identity and actual environment concerns.
17 final checkpoint assertions and6 launcher tests pass. Real7group pilot paused
at2, then resumed remaining5: first4files retain hashes AND modification times.
5successes/2explicit numerical failures. Completed original source data untouched:
1400campaign files,20old sources,9saved analysis artifacts checked without changes.
New batch tools use cached fields and saved positive-event HDF5 plus full zero ledger.
Full23693group inputs were prepared at .local/cs137-1m-native. The first2 actual
production groups176/457 completed and were checkpointed; the detached full worker
was started2026-09-27 at13:27 CDT to RESUME those results, not restart them.
Inspect progress.json, launcher.json and actual workers; no new field solves. Do not rerun source transport or the completed pilot.
See tools/NATIVE_RESPONSE_FIX.md and .local/native-response-fix for exact evidence.

## Native progress-display recovery (2026-09-27)

The native worker stopped after1870 committed groups on progress.html rename EACCES,
not during physics or result commit. All1870 binaries/DONE hashes were verified.
An additive display-only adapter now retries/defer sharing failures; scientific
commit/recover, settings, source hashes and field caches remain unchanged.
17 Julia assertions and5 Python tests passed; two existing scoped reviewers checked
this recovery. The child-ownership finding was corrected and rechecked.
A real resume processed only ONE new group and paused at1871 with exit0. All3747
pre-existing protected files retain hashes/sizes/modification times. No old groups
were recomputed;27 existing numerical failures remain separate from this IO fault.
Use tools/resume_native_progress.py and the updated native Resume.cmd, not the old
launcher. The frozen numerical configuration was NOT rebased. Extension hashes live
in .local/cs137-1m-native/progress-recovery.json. Evidence: .local/native-progress-recovery.
Resumed at2026-09-27 17:08 CDT through the display-resilient entry. Live check
confirmed progress beyond1871 with status running; no Geant4 or new field solve.
Use live progress/launcher/exit records, not a remembered PID. Wait for completion.

## Native contact-start compatibility recovery (2026-09-28)

The resumed worker later stopped after 13,841 committed groups at SAP22 event128042/group0:
positive row2248 is inside retained Geant4 Ge but inside SSD point contact1. A full saved-input
scan found AK02=0 and SAP22 exactly5 affected events/groups,38 positive rows, all contact1.
Both existing reviewers approved fail-closed group handling: no coordinate shift, no partial-energy
subtraction and no assumed immediate collection. The entire affected group keeps truth/identity
while native/readout remain null under failure_class=input_domain_compatibility; exterior deposits
remain fatal and ordinary groups use the unchanged response.

19 Julia assertions pass. max_new=0 recovered all13,841 groups and paused exit0; max_new=1
committed only event128042 as the typed input-domain failure. A full after-check rehashed all
13,841 prior DONE/JLS files and confirmed hashes, sizes and modification times unchanged.
The original runner/config/cached fields remain frozen. The updated local Resume.cmd selects
`tools/resume_native_contact.py`; see tools/NATIVE_CONTACT_START_RECOVERY.md and
.local/native-contact-start-recovery. During the live run the legacy numerical_failures field is
an aggregate native-failure count; final analysis must separate input-domain, boundary-numerical
and electronics rejection categories. The full worker resumed through the separately bound
contact-safe entry at 2026-09-28 10:45 CDT and finished at 12:41 CDT with numeric exit0.
All23,693/23,693 groups are committed; completed checkpoints were reused, not rerun.

## Completed million-event native response and final engineering spectrum (2026-09-28)

The saved 1M-per-detector transport is now processed through native SSD drift, synthetic
electronics and peak ADC for every23,693 positive pulse group. COMPLETE is
completed_with_native_failures with21,672 accepted,1,613 readout rejects and408
native/input-domain failures. No Geant4 source transport or field solve was repeated.

Per model: AK02=12,420 groups:127 boundary stalls,1,536 below-threshold readout rejects,
10,757 accepted. SAP22=11,273 groups:276 boundary stalls,5 contact-start input-domain
failures,77 below-threshold rejects,10,915 accepted. Unknown native/input failures remain
null responses, not zero-energy events. AK02 retains12,235 native-completed groups with
step-limit flags; SAP22 retains92 groups with stopped-without-contact flags.

The final scalar audit v3 re-bound all23,693 DONE/JLS checkpoints to the hash-checked
frozen input JSONL, including input-line hashes and embedded event/group hashes. It
verified about3.66GB of committed result files. The final response report joins these
records one-to-one to the saved Geant4 truth classifier and verifies the classifier
ledger hash. Six report tests pass, including complete group identity, response/failure
partitions, histogram bins+flows and line-full accounting. Two existing independent
reviewers closed the final integrity/physics review with no blockers.

For saved 660-663keV line-photon full-containment candidates: AK02 has806 truth groups,
2 native failures and804 accepted;630 accepted responses remain in [650,670)keV.
SAP22 has531 truth groups,6 native failures and525 accepted;514 remain in [650,670)keV.
These are engineering broad-window counts, not photopeak fits, efficiencies, physical
FWHM or calibrated CCE.

Public result: docs/examples/cs137-1m-response/report.html. The existing 1M Geant4 truth
page links to it. Publication contains only summary/histograms and all23,693 scalar
group records; raw3.4GB JLS checkpoints remain local. The full site snapshot validates
1325 files,745855440 bytes,31 HTML pages and1776 local links. Final publication tooling
is tools/analyze_native_complete.jl, native_final_report.py,
native_response_publication.py and updated build_site.py/check_site.py.

## Current roadmap (full owner-approved scope)

Owner reaffirmed this COMPLETE roadmap on 2026-09-28. An immediate launcher test
must not replace the website/low-code deliverables below. Foundation v1 is not
acceptance of the full visitor experience. Use saved outputs, not new campaigns.

1. **COMPLETE / PRESERVE:** 1M/model Geant4 truth, native SSD, synthetic electronics
   and peak-ADC response, final analysis and published reports. Protect original
   LH5/HDF5, inputs, fields, checkpoints, failure ledgers and old examples.
2. **COMPLETE BOUNDED ACCEPTANCE:** saved-positive guarded-entry regression using
   explicitly test-only verified cached fields; same-machine source-only clone
   negative preflight. See tools/LAUNCHER_ACCEPTANCE.md for executed evidence and
   limits. Positive uninstrumented Run.cmd orchestration, cold setup and a public
   saved-input/cache-import interface remain NOT_VALIDATED / future work. Do not
   add those new features solely as a gate to saved-data-only Pages improvements.
3. **DELIVERED / GITHUB PAGES FIRST-VISITOR ROUTE:** independently audited and
   discussed with the original site-UX/workflow agents. Three main entries have lightweight
   SAVED geometry, signal and spectrum previews. Move detail into second/third
   levels: concise overviews, gallery and technical pages for all 17 models; organized
   detector/result/scenario/methods/download hubs. Preserve all model downloads.
   Fix duplicate detector navigation, ambiguous 10k links in 1M sections and stale
   guide wording. Clearly distinguish initial decays, pulse groups, truth, native
   charge, electronics, 10k examples, 1M results and curated/all-record selections.
   Preserve legacy URLs and meaningful fragments, including contact legends.
   Update README and one maintained Setup/Run/Open Results guide, with honest
   prerequisites, offline/fetch behavior and validation status. Verify repeat-build
   idempotence, unique IDs, links/fragments and desktop/mobile/keyboard journeys.
   Do not merely add more homepage announcements or call generated HTML acceptance.
4. **DELIVERED LIGHTWEIGHT SSD GEOMETRY:** all 17 catalog models have saved-surface rotation,
   zoom and per-contact toggles, including all 34 GeGI contacts. Continue preserving controls,
   small contacts and fallback behavior. No browser ParaView replacement is needed.
   Additional saved fields/weighting potential/drift interaction is optional later
   work, never a new prerequisite. Keep real coordinates and display transforms
   distinct; do not fabricate unavailable trajectories or ship million-event JSON.
5. **LOW-CODE COMPLETION AFTER PAGES:** Setup/check -> select detector/cryostat/
   source/events -> validate/save settings -> run -> progress/pause/resume -> results.
   Start with reviewed LBNL Cs137 AK02/SAP22; unsupported scenarios are not executable options.
   Add additional physically compatible detector replacements through an explicit
   geometry/placement/readout adapter, not only a viewer dropdown. Keep the full
   selected detector configuration consistent across every downstream stage.
   Organize simple defaults and advanced preamp/shaping/pole-zero/sampling/ADC
   settings in the ELECTRONICS stage. Save effective parameters, units, identities
   and provenance. Reuse earlier stages only when their dependencies match.
   Improve novice errors/log access and implement/test finer native recovery before
   claiming per-group resume. Track positive uninstrumented launcher and explicit
   saved-input/cache reuse acceptance here; do not invent historical run receipts.
   Completed this bounded prerequisite: shared required artifact/source inventories,
   native/profile settings, rehashed-mutation checks and read-only terminal inspection.
   Finer recovery and editable electronics settings remain separate future work.
6. **THEN / PERFORMANCE:** inspect saved stage timings, then bounded benchmarks
   of Geant4 threads/chunks, IO/compression and SSD parallelism/GPU suitability.
   Record resource costs and numerical/statistical parity tolerances. Do not rerun
   1M to benchmark, silently drop records, or change uncollimated source sampling.
7. **LATER / EXTENSIONS AND ACCURACY:** independently reviewed GeGI/large-cryostat
   adapters only with actual available geometry. Compare the owner's SAVED SPECTRA
   with documented apparatus/source/electronics metadata; measured pulse waveforms
   were not retained. Li profile/lifetime, grid/parcel uncertainty and calibration
   remain bounded accuracy research, not global delivery-blocking PDE gates.
8. **THROUGHOUT / MAINTAINABILITY:** one readable project and authoritative handoff;
   separate code/models, public derivatives, permanent science and rebuildable
   temporary output. Never blanket-delete .local or erase failed evidence. Edit
   generators rather than generated pages; preserve old links/data; record tests,
   scoped reciprocal reviews and milestone commits without resets or API billing.

## Current limitations, not reasons to block every engineering feature

SSD 0.11.8 already contains the published native Li/RCC machinery; experimental
validation exists elsewhere. AK02-specific profile/lifetime calibration is not established.
Native diffusion produced nonzero signals for events 41/78 that were zero in the
legacy no-diffusion replay. N/seed variation and finite trajectory caps remain visible.
The frozen default readout still rejects ANY negative cumulative charge. The explicit
`signed_input_positive_peak` policy now accepts otherwise valid positive peaks while
retaining negative-input and all independent diagnostics. Low/saturated/gate-limited
peaks still reject. Neither policy rectifies charge or calibrates against event truth.
The recorded ~15-percentage-point transition response sensitivity and failed global
field-agreement tests remain unresolved. Numerical parcel spread is not physical FWHM.

## Historical delivery plan (superseded by the current roadmap above)

1. **Completed: configurable peak validity.** Legacy preserved; signed-positive
   policy, finite gates and independent diagnostics tested.14 paired native cases
   retained exact charge and legacy numerics; gate-interval and identity mutation
   issues found by reciprocal reviewers were fixed. This is engineering validity,
   not calibrated CCE. The general native entry is delivered in step 2.
2. **Completed: reusable native entry and profiles.** `native_response.jl` reuses
   one SSD field solution per model/configuration. Full signed scalar/endpoint
   census, independent injection calibration, explicit ADC/profile/gate settings
   and bounded offline traces are implemented and tested.
3. **Completed nominal integration: cryostat and Cs137.** Native import, materials,
   transforms and sampled overlap checks passed. Original LBNL bytes are intact.
   Capsule/spacer/pose are explicitly nominal, not as-built. Initial-decay
   daughter clocks, parent IDs and finite isolated windows are retained. World
   air is unscored and full energy closure remains null.
4. **Completed with explicit native failures: event-complete 10k/model.**
   Use the existing `cs10000-v2/comparison.html`, response ledgers and receipts.
   The 500/model pilots and strict failed `cs10000-v1` remain unchanged. The two
   record-mode native failures are unresolved and separately counted; completion
   is functional integration, not calibrated physical accuracy. Next work is
   inspection of the SAVED comparison and, only for a concrete new requirement,
   bounded analysis of the existing anomaly records. Do not repeat transport,
   field solves, 500 pilots, 10k runs or review campaigns because ChatGPT showed
   Thinking failed. 100k is not scheduled or authorized by this recovery.

### Historical anomaly work (completed/bounded checks recorded above)

First inspect the EXISTING anomaly records: AK02 event 8432 and SAP22 event 8413
are both 31.818831554318052 keV deposit groups rejected for a noncontact exterior
endpoint. Reuse the preserved AK02 diagnostic; only a targeted missing reproduction
or concrete fix should launch new calculations. Do not rerun both 10k campaigns.
Also assess the effect of trajectory caps: 119/120 successful AK02 native groups
are step-limited; SAP22 has 1/114 stopped-without-contact. ADC acceptance is not
complete collection. Keep the frozen baseline and failure records unchanged.
Then use actual source/holder dimensions and electronics/spectrum metadata for
experimental calibration. No measured waveform recovery is possible or required.
Do not scale to100k until a specific statistics goal and response-quality/resource
review justify it; global Li/PDE convergence is still not a functional gate.

5. **Accuracy lane, bounded and separate.** Calibrate profile/lifetimes, numerical
   parcel error, field/grid sensitivity, real electronics/noise and measured spectra.
   Quantitative physical claims wait for relevant checks. Exploratory labeled runs
   and useful software delivery do not wait for every global PDE research question.

## Working rules for the next conversation

Use this handoff plus the relevant small source modules, not the full historical
chat or entire debug JSON. Before writing, inspect Git status and actual processes;
respect `.local/autonomy/state.json` and its owner lock. A clean student clone
needs no private supervisor state. Keep one bounded deliverable per round; use
focused independent physics/integrity review for meaningful code changes, not a
new review campaign for every documentation or display edit.
Keep console output short, write detailed evidence to files, and close owned idle
REPLs/test browsers at the end. Do not delete user chat records, authentication
storage, global shell history, raw runs or reviewer evidence as a performance fix.
Update this page in place. Commit meaningful milestones; Git history retains the
long audit trail. Preserve unresolved findings without letting new global research
gates silently replace the flow-first delivery plan.

## Interruption recovery checkpoint

The 2026-09-26 chat failure left supervisor state stale after the run completed.
Recovery evidence and prior handoff/state backups are under
`.local/peak-native-delivery/recovery-audit/`. Read final receipts and actual
processes before any restart; an interface failure is not a computation receipt.
The next conversation starts from the CURRENT header and saved final 1M response results, not the historical 10k plan. Stream polling failure is not a simulation failure receipt.
