# Current project state and next steps

Updated: 2026-09-26. This is the short, maintained handoff, not an append-only log.
Latest scientific/software release: **v0.14.0-native-li-readout**, commit **0d462ad**.
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
The frozen synthetic readout rejects ANY negative cumulative charge, including small
stochastic excursions. A positive shaped peak can therefore have null ADC Erec.
Do not rectify charge or delete rejection flags to make it pass.
The recorded ~15-percentage-point transition response sensitivity and failed global
field-agreement tests remain unresolved. Numerical parcel spread is not physical FWHM.

## Delivery plan, in order

1. **Configurable peak validity and native entry.** Preserve the exact legacy policy;
   add an explicitly selected signed-input/positive-peak policy without rectification.
   Preserve independent clipping, threshold, negative-excursion and transport flags.
   Validate synthetic signed/zero/saturated/delayed pulses and repeat the 14 native cases.
   Acceptance means correct causal readout/accounting, not agreement with deposited truth.
2. **Reusable native AK02/SAP22 comparison and readout profiles.** Start with 100
   primaries per detector and measured cost; reuse native SSD, existing fields and
   electronics, not another solver. Add versioned preamp decay/capacitance, shaping
   time/gain/pole-zero, ADC range/bits/threshold/gate settings with independent pulser
   calibration. Show stage-by-stage signals/energies; keep analog and digital branches distinct.
3. **Cryostat and Cs137 source contract.** Reuse the pinned LBNL geometry after
   material/transform/overlap checks. Source capsule, placement, holder and crystal
   orientation must be surveyed or explicitly nominal, never silently called as-built.
   Validate parent/daughter IDs, delayed Ba137m emission, finite electronics windows
   and radioactive energy bookkeeping; this is not a 662 keV monoenergetic substitution.
4. **Event-complete large run.** Implement streaming/chunks and reuse one validated
   field solution per detector/configuration. A 500-decay capacity pilot precedes
   10,000 initial Cs137 decays per detector; consider 100,000 from measured time,
   memory, output size and statistical benefit. Save every scalar record and bounded
   trace examples, not 100,000 browser traces. Compare all stages and final spectra
   with per-decay/per-emitted-photon/per-accepted-pulse normalization distinguished.
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
