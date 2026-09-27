# Current project state and next steps

Updated: 2026-09-26. This is the short, maintained handoff, not an append-only log.
Latest tagged release: **v0.14.0-native-li-readout**, commit **0d462ad**.
Latest committed implementation: **c037558** (native profiles and Cs137 campaigns).
Peak-policy milestone: **337c841**. Completed 10k/model results are verified below.
Read this file first in a new conversation; verify actual Git/process state before writes.

## Preserved history

The complete pre-cleanup development log is preserved [at its immutable Git commit](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/0d462ade58edcd75aa25aed18056e420967239c8/PROGRESS.md).
An exact local backup is `.local/maintenance-context/PROGRESS-before.md`.
Raw runs, source hashes, review exchanges, failures and release tags remain intact.
Consult only the relevant historical section when needed; do not reread the whole log.

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

Next bounded work is the saved-HDF5-to-native bridge and representative pilot,
retaining zeros/identities/caps/anomalies, before any long native response run.

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

## Delivery plan, in order

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

### Next bounded work (after the saved-results publication)

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
The next conversation starts from completed 10k results, not plan item 1.
