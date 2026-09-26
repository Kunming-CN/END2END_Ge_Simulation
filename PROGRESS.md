# Current project state and next steps

Updated: 2026-09-26. This is the short, maintained handoff, not an append-only log.
Latest tagged release: **v0.14.0-native-li-readout**, commit **0d462ad**.
Latest committed peak-policy milestone: **337c841**. Native campaign work below is newer.
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
- The reviewed record-mode **10k/model rerun is active** in
  `.local/peak-native-delivery/cs10000-v2`, supervisor PID 18068. Native failures
  remain unknown responses, not zero charge or electronics threshold rejections.

Entry points: [library](https://kunming-cn.github.io/END2END_Ge_Simulation/),
[full engineering example](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/pipeline.html),
[native Li to readout](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/native-li/comparison.html),
[accuracy diagnostics](https://kunming-cn.github.io/END2END_Ge_Simulation/lithium/lithium.html).
Local native example: `.local/native-li-example/comparison.html`.
Important source: `simulation/native_li_example.jl`, `simulation/readout.jl`,
`simulation/replay.jl`, `tools/pipeline_demo.py`; see module READMEs for commands.

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
4. **In progress: event-complete 10k/model.** The 500/model positive pilot and
   measured resource check passed. `tools/run_native_campaign.ps1` launches
   serial detector stages; the full dependency/artifact pilot guard now also
   rejects missing artifacts before allocating a large-run output. Local offline
   report: `tools/native_campaign_report.mjs`; commands in `tools/NATIVE_CAMPAIGN.md`.
   Preserve failed strict cs10000-v1. The tested extension and clean cs500-v4
   pilot authorize the active cs10000-v2 rerun. Wait for actual complete receipts,
   audit every count/failure, then export/inspect its final comparison and record
   results. Do not alter computational source during this run or overwrite evidence.
   100k is not automatically scheduled; it remains resource/statistics-dependent.

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
