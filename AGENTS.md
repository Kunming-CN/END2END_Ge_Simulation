# Project working rules

Work only in this project unless a recorded input dependency needs a read-only check.

1. Read README.md and PROGRESS.md first. Complete one milestone-sized task at a time.
2. Keep one project root. Use tools/ for reusable tooling, docs/ for public results, and .local/ for disposable local evidence/backups. Do not scatter copies, timestamped reports or extra environments.
3. Preserve existing numerical data and model hashes. Never silently change bias, impurity, geometry, carrier physics, missing-charge labels or event selection to make a test pass.
4. The public repository initially contains the exported website and maintenance tools only. The full raw computation workspace is deliberately ignored. Add new calculation source deliberately during M1, not with a wholesale force-add.
   Intentional M1a addition: `models/` contains exact versioned SSD model snapshots and inspected relative includes. Preserve original YAML bytes and pinned hashes; keep provenance portable and reference/candidate limitations intact. Original model/cache folders remain ignored.
5. Never publish credentials, private paths, raw field caches, manuals, photographs or slides without a specific reason and review. Do not change permissions or enable a public service unrelated to this project.
6. Geant4/remage provides radiation deposits, positions, creation times and identities. SSD provides semiconductor drift and electrode signals. Readout is a separate stage. A deposition time is not a drift time.
7. Keep all relevant deposits of one event grouped. Keep truth Edep separate from readout-derived Erec. Do not set the energy gain separately for each event.
8. Reuse existing SSD, ParaView and remage functionality. Do not introduce a second frontend framework, Docker, a VM or another solver solely to publish static results.
9. Record exact software versions and random seeds. Distinguish smoke tests, numerical convergence, and agreement with experiment.
10. Before committing: rebuild/validate the relevant outputs, inspect the diff, update PROGRESS.md, and commit a meaningful milestone. Push without force; stop for conflicts.

## Existing tools

- `tools/build_site.py`: deterministic export of the locally generated library into docs/.
- `tools/export_models.py`: explicit `--import` of recorded originals; portable `--validate` of versioned snapshots. Site model downloads use `models/` only. Unexpected managed edits must fail, never be overwritten.
- `tools/smoke_test.jl`: bounded AK01 event replay in the existing Julia environment.
- `tools/smoke_scene.py`: existing AK01/GeGI native-state reload and render.
- `tools/migrate_paths.py`: explicit old-root replacement with an originals ZIP; do not rerun blindly.
- `Publish.cmd`: approved publication workflow. Browser authorization may require the owner.

Do not claim that Work/Codex has been started merely because these instructions exist. The execution environment and actual working directory must be verified in that session.

## Work/Codex model preference

The maintainer requested Astra with High reasoning for this project's Work/Codex tasks (2026-09-25).
- Use model `gpt-6-astra` with `model_reasoning_effort = "high"`.
- The development computer's user config already has both values; do not replace the entire config or change unrelated settings.
- When launching Codex programmatically, explicitly select the same model and reasoning level so another profile or task preset cannot silently change them.
- If using Plan mode, set its supported `plan_mode_reasoning_effort` override to `high` for that run as well.
- For Work/Codex graphical sessions, verify Astra and High in the session's model control; a project instruction alone is not a model-setting mechanism.
- Astra High remains default. The maintainer permits supported XHigh or stronger reasoning for difficult bounded reviews; specify and record effective settings. Do not enable separately billed API usage or Fast mode without approval. Never trigger, confirm or consume any banked reset/reset credit; only the owner may do that.
- Confirm the effective model, reasoning level and project directory when starting a development task. Configuration verification is not a claim that a task has been launched.

## Publication validation

Run tools/test_site.py and tools/check_site.py before publishing. Build only through tools/build_site.py; never hand-edit docs/. Verify the live build with tools/check_site.py --url after deployment, rather than relying on the publisher's basic reachability message. Keep the public manifest and exact-byte Git attributes intact. The original numerical workspace remains out of scope for a publication-only edit.

## Portable CPU example

M1a includes only the reviewed simulation/Project.toml, Manifest.toml, run.jl and README.md. Keep this environment separate from the preserved full campaign. Run --check-models and the bounded cache-free example before changing the lockfile or runner; log any differences. Generated files belong under .local/, not models/, simulation/ or docs/. The canonical model snapshots are deliberately frozen by reviewed hashes; do not silently mutate them.

## M1b compute and transport boundaries

Use the shared simulation/run.jl for both CPU and optional CUDA. CPU remains installable without CUDA. Never silently fall back from a requested GPU or force partial charge to unity. Report potential-solve and end-to-end times separately; warm-up is not production timing. Before upgrades run parser/model tests, CPU regression and the explicit parity benchmark. Do not loosen comparison gates to force a pass.

transport/ keeps the Pixi manifest/lock and toy installation checks; large environments belong to Pixi’s detached Linux cache. Preserve cryostat-source.json provenance and locally cached upstream bytes. No LBNL geometry or drift/recombination validation may be inferred from the toy Ge-box smoke test. Keep coupling pending until geometry/units/event mapping are independently checked.

## M2 scope and independent review

AK02 (Anupama ICPC2) is the Li-contact primary case; SAP22 is a non-Li cross-check, not a matched-geometry experimental control. Defer new GeGI work. Preserve original 78 K / +500 V and +700 V snapshots; first reproduce them, with any nominal 77 K override explicit and consistently recorded. No invented experimental holder/source positions or uncalibrated lifetime claims.
Read-only research elsewhere under My Drive is authorized; never edit unrelated files. Keep raw transport energy separate from charge response; no double Li loss. Preserve event IDs, deposition times, transforms, zero-deposit primaries and incomplete-collection flags.
After bounded implementation/testing, use two separate read-only review sessions: (1) HPGe and electronics, (2) particle transport and event integrity. Give both the same tested diff/evidence, then exchange findings for cross-review. Summarize confirmed issues and resolutions in PROGRESS.md. These are AI reviewers, not human certification. Never claim independent agents ran unless launched.

## Successive authorized rounds

The owner requested successive bounded rounds without per-round approval (2026-09-26).
Scheduled continuation may be enabled separately; verify its live enabled state and
actual tool capability rather than assuming it can execute. Before an automated round, inspect
`.local/autonomy/state.json`, its lock directory, the Git worktree and actual
project worker processes. Never run two supervisors/rounds concurrently. Only an
explicit ready state with no prior active supervisor/workers/lock permits a new
round; acquire the lock before writes. Stale or conflicting state requires
inspection, not blind lock deletion. On completion, record tested outcomes and
next bounded work, synchronize Git, release the owned lock and leave ready.
Unknown experimental dimensions block claims that require them, not unrelated
mathematical verification. Notify the owner only for substantive progress or an
issue genuinely requiring their intervention. Usage limits never authorize resets.

The scheduling state/lock governs the owner's automated continuation only. A clean
student clone does not need this private state to run documented CLI examples or
make manual contributions; normal source/test/review rules still apply.

Owner-confirmed data availability (2026-09-26): original AK02/SAP22 measured pulse
waveforms were not saved; only energy-spectrum data remain. Do not fabricate
waveform comparisons or require recovery of nonexistent files. Spectrum-only
validation must retain acquisition/background/calibration metadata and model
identifiability limits. EM-constructor changes affect radiation transport, not
SSD carrier physics; compare with fixed settings and statistical controls.

## Geometry publication and direct SSD checks

Use `tools/render_contacts.py` for staged geometry-only changes; never run the
full numerical gallery builder merely to recolor contacts. Preserve all meshes,
model hashes, cameras and non-geometry outputs. Review full-size and thumbnail
views, including tiny point contacts; keep categorical ID/name/bias text and a
full-size link. Do not infer doping or Li thickness from the color key.

Keep the applied-index/source provenance checks and backed-up apply transaction.
Intentional palette changes require an explicit reviewed full-detector upgrade;
ordinary publication must never silently rebaseline changed numerical sources.
Run `tools/test_contacts.py` with the existing publication tests.

`simulation/verify_ssd_electrostatics.jl` verifies only the synthetic homogeneous
source-free annulus using SSD itself. Retain separate interior/contact-interface
errors, native-stencil checks and independent-FV diagnostic interpretation. A
passing simple benchmark does not clear the unresolved production Li/depletion
gates. Keep reviewer resolutions and exact tested hashes in the round evidence.

## Final goal and critical-path priority (owner audit, 2026-09-26)

First close the minimal reproducible radiation -> charge -> preamp -> analog
shaper -> peak-ADC -> reconstructed-energy workflow and provide a traceable
example. Advanced Li/finite-conductivity/source-geometry validation is a parallel
accuracy lane, not an indefinite prerequisite to a clearly labeled engineering
demo. Do not mark unresolved physical gates complete when the pipeline runs.

Keep all selected primary IDs, zeros, raw-row provenance and charge endpoint
flags. A readout threshold changes validity/selection, never the event census.
Calibration must be from a separate synthetic injection or measured calibration,
not per-event Edep. Preserve charge/current/voltage/ADC units and distinguish the
analog numerical time grid from a waveform-digitizing acquisition system.

Run one orchestration entry with one generated output root. Showcase export must
read completed, hash-checked artifacts without simulations or external frontend
dependencies. Maintain an offline event explorer with explicit settings, low
statistics and limitations; no fitted experimental claims without actual data.

## Resource-conscious standard examples

Use bounded named monoenergetic presets and explicit per-run overrides rather
than editing canonical detector/electronics inputs. The only allowed change in
a generated readout configuration is its expected primary count. Verify that
restriction independently of file hashes, including deliberately rehashed edits.
Keep models and stages serial; default to two Julia threads, allow one for
low-load work, and bound the selectable thread count. Child-only thread-pool
settings must not change systemwide settings or close unrelated user programs.

Compact public JSON must preserve every event, numeric value, flag and deposit.
Do not reduce precision or silently sample events to make pages smaller. Keep
raw reports readable and bind the compact export to its exact serialization and
template hashes. Defer heavy detail rendering until the panel is opened. Confirm
offline/mobile behavior and current selection when details open or refresh.
Measure before claiming a speedup; distinguish sampled timing from guarantees.

## Li diagnostics and future source campaigns

Preserve geometric-contact flags separately from conditional Ramo completion
budgets. Small weighting-potential remainder is not proof of recoverable charge.
Native diffusion studies must record the zero-field termination setting and use
independent parcels so boundary handling does not silently retime another cloud.
Keep numerical parcel uncertainty separate from physical energy-resolution noise.

Retain the original loose screens and explicitly label additional post-run
paired-seed analyses; no screen pass establishes transition-grid convergence.
Use `tools/lithium_report.py` to export checked raw diagnostics into the stable
`.local/lithium-report` bundle; do not manually edit generated website figures.

Before large Cs137 runs, test ion-decay identities, delayed daughter timing,
finite electronics windows, energy accounting, geometry assumptions and streaming.
A 500-decay cost pilot precedes 10k per detector; 100k is conditional on measured
resources/statistics. Adjustable readout profiles require independent injection
calibration and must preserve the frozen demonstration regression.

## Native transition-grid audit

Use `diagnose_transition_grid.jl` for fixed-state residuals and explicit nested
candidate grids; do not alter the production runner to hide the Li discrepancy.
Both red/black groups must be checked, with frozen-alpha source scaling distinct
from depletion-clamp checks. Restore saved alpha for an audit and clear derived
classification bits before re-marking copied-back state. Record repainting of an
initial guess separately from final contact-member-node errors.

A native fixed-point pass is not grid/PDE/CCE convergence. Preserve partial
statuses and cold-start budget failures; an unconverged initial guess cannot prove
multiple equilibria. Actual grid spacings and source masks—not minimum-spacing
parameter labels—govern comparisons. Next tests should isolate initialization
and crossed radial/axial grids before further radiation statistics.

## Initialization/axis attribution and stopping rules

Keep `diagnose_transition_axes.jl` separate from the pinned production/native-grid
helpers. Same-grid coefficient identity excludes only initial potential; verify
fresh alpha, independent storage and unchanged parent hashes. Contrast acceptance
requires an accepted E22 reference, not just accepted endpoints. All crossed
vectors share pointwise max(1 V/cm, norm(E22)) normalization.

Completed attribution diagnostics is not global initialization agreement or Li
CCE convergence. Preserve whole-domain and semiconductor-localized differences
without dropping exterior nodes from the original gate. Midheight z spacing was
unchanged in the tested axial refinements; do not generalize their small onset
effect to all axial resolution. Next work is one bounded paired continuation,
then fixed-z radial stencil/source-quadrature diagnosis, not unlimited retries.
Physical literature/calibration and numerical verification must remain distinct.

## Owner's time/scope challenge and native delivery correction

Do not resume open-ended global PDE audits as the prerequisite for a labeled
engineering example. SSD already implements RCC transport and published work
includes measured-spectrum validation. Preserve numerical failures, but distinguish
quantitative accuracy from functional integration. Report measured calculation
runtime separately from coding/review/tool/publication wall time; do not explain
an entire ten-hour interaction as necessary detector compute without profiling.

Use the bounded native_li_example.jl for selected native diffusion-to-electronics
work. It leaves the legacy producer untouched. Keep original IDs, row delays,
weighted charge, seeds, signed signals and rejection/cap flags. No small-parcel
variation may be called physical resolution, and no example is calibrated Li CCE.
Reviewers must not claim reciprocal discussion or test execution without records.
The full2026RCCpaper includes an experimental BEGe comparison; analytic-only is
an incomplete description. No further diagnostic round is automatically authorized
as a critical-path gate merely because a stricter criterion can be formulated.
