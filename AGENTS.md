# Project working rules

## Owner update — 2026-10-22 continuous planned development

Continue automatically through the existing full-chain repair and software plan.
Deliver and record milestones, then start the next authorized step without waiting
for routine confirmation. Stop only when a concrete decision requires the owner.
Keep calculations bounded and originals intact; monitoring remains PAUSED and
large-sample campaigns remain after full-chain validation. No resets or extra AI
review rounds. Root owns direction/quality; gpt-6.1-sol ultra handles concrete
development tasks with simple code and direct writing.

## Owner update — 2026-10-20 bounded repair autonomy

The owner said "不需要每次等我审核，你继续就行" after the bounded GeGI
field-validation requests. Proceed autonomously with necessary small calculations,
development and publication within the existing full-chain repair objective;
do not ask for approval every round. Keep each calculation bounded, measured and
restartable, preserving originals and failures. This supersedes the per-calculation
approval gate for this repair. Large-sample campaigns remain after full-chain
validation; monitoring stays PAUSED and no reset is authorized.

## Owner update — 2026-10-20 planning, evidence and token use

The supervisor owns the full-chain plan and critical decisions. Use gpt-6.1-sol
for ordinary retrieval, organization and development; reserve gpt-6-astra for
necessary complex analysis/planning. Avoid multiple Astra workers, redundant
context reads and repeated checks. Scope each delegated task to one concrete
deliverable and reuse completed evidence. No additional AI review rounds.
Prioritize the owner's private GeGI/Ge-STAR presentations and detector data
analyses, supplemented by manufacturer specifications/manuals/reports and primary
literature. Map evidence to the exact detector/version and simulation stage;
related detectors inform methods, not GeGI parameter values. Establish a correct
small complete simulation workflow before recovery refinements or large samples.

## Owner update — 2026-10-20 product language and implementation pace

Use direct, useful language in the GitHub website, software and guides. Explain
results, controls and next actions. State material assumptions, sample counts and
uncertainty once where they affect interpretation; put detailed methods and
provenance in the relevant detail view. Remove repetitive disclaimers, defensive
justifications and internal workflow commentary from the main user journey.

Keep implementation small and concrete. Validate external inputs and scientific
stage boundaries, then reuse the validated result. Add checks for identified
failure modes; avoid duplicate validation in hot paths, speculative compatibility
layers, broad exception handling, silent fallbacks and unnecessary approval steps.
Preserve units, original data, failure/null accounting and necessary reproducibility
checks. Simplification must retain accurate scientific meaning and actionable errors.

## Owner extension — 2026-10-17 GeGI integration

Build a dedicated GeGI cryostat at the same assembly level as LBNL, accepting
only the exact GeGI detector. Use the supplied dimensional references and Ge-STAR
presentations read-only, with primary online references where needed. Integrate
actual configurable transport, multichannel charge/readout, Compton cones and
directional imaging in the existing desktop workflow. Keep truth-assisted and
signal-derived reconstruction explicitly distinct. Test figures may be published
through the existing website generator; do not bundle precomputed demonstrations
in the student software. This authorization supersedes old instructions to defer
GeGI and the completed P0-P5 stop boundary for this new feature only.

Plan small complete milestones, reuse existing solvers and saved applicable data,
measure before scaling simulations, and parallelize independent implementation
while bounded calculations run. Simple development tasks may use gpt-6.1-sol;
difficult geometry/reconstruction tasks may use gpt-6-astra, both explicit ultra.
No additional AI review rounds. Ask only for genuinely blocking missing inputs;
record nominal assumptions without claiming as-built or experimental validation.
Synchronize completed source, student release and requested website results with
GitHub. All prior data-retention, environment and no-reset safeguards remain.

## Owner correction — 2026-10-14 (current authority)

This update supersedes every older AI-review requirement below and in plans,
automation prompts or historical handoffs. Do not launch extra review agents,
physics/workflow/third-party review rounds, peer debates, direction committees,
or repeated broad audits. Ordinary development checks remain: run only tests
relevant to a concrete change, check required units/identities, inspect the diff,
and deliver. Do not use review counts as evidence of user value.

The priority is student use: software-only download, configure compatible
cryostat/detector/source with the mouse, run/stop/resume, and find actual data.
Do not make another canned engineering demo the next delivery. Reuse completed
work and upstream remage/SSD functions; do not rebuild already accepted features.
Phone work and second-computer acceptance are excluded. Address actual feedback.

New student-facing result/analysis outputs must not contain a per-event parade
of zero-input records or fabricated zero waveforms. Keep initial/zero/nonzero/
failed/rejected totals, original nonzero IDs, denominators and seeds so filtering
does not alter efficiency. Existing original scientific ledgers/campaigns remain
unchanged; changing new storage formats is a separate explicit implementation.
Do not delete old scientific originals as part of temporary-file cleanup.

Remove proven disposable assistant-generated AI review files, browser fixtures/
screenshots, duplicate software ZIPs and synthetic acceptance scratch, retaining
one compact cleanup manifest. Preserve production dependencies, canonical models,
raw transport/native/readout data, unique physical failures, user inputs, chat
histories and installed environments. A filename containing example or test is
not proof it is disposable: production currently imports/hashes several of them.
Never follow a junction/reparse point during cleanup. Verify absolute deletion
paths and delete only the explicit owned candidates. Do not generate more report
piles or save complete chat transcript copies for this reconciliation.

Owner continuation update (2026-10-14): start the corrected plan and restore the
updated scheduled task. It must use the student-first/no-extra-review queue, not
stale PSD3/audit instructions. P2 permits a small actual software acceptance run:
start with 100 initial events, cap total new primaries at 500 and use one detector/
source combination. Reuse existing geometry/fields when applicable, record the
configuration/seed, and preserve failures; no enlarged campaign or repeated
seed changes to manufacture a pass.

Work only in this project unless a recorded input dependency needs a read-only check.

1. Read the compact PROGRESS.md handoff first, then only relevant README/source sections. Complete one milestone-sized task at a time. The current handoff governs delivery order; older stage notes are historical accuracy guidance, not automatic blockers.
2. Keep one project root. Use tools/ for reusable tooling, docs/ for generated public results, and .local/ for classified local data/evidence. Completed science and unique failure records under .local/ are permanent, not disposable; follow tools/DATA_RETENTION.md and tools/LOCAL_WORKSPACE.md. Do not scatter copies, timestamped reports or extra environments.
3. Preserve existing numerical data and model hashes. Never silently change bias, impurity, geometry, carrier physics, missing-charge labels or event selection to make a test pass.
4. The public repository initially contains the exported website and maintenance tools only. The full raw computation workspace is deliberately ignored. Add new calculation source deliberately during M1, not with a wholesale force-add.
   Intentional M1a addition: `models/` contains exact versioned SSD model snapshots and inspected relative includes. Preserve original YAML bytes and pinned hashes; keep provenance portable and reference/candidate limitations intact. Original model/cache folders remain ignored.
5. Never publish credentials, private paths, raw field caches, manuals, photographs or slides without a specific reason and review. Do not change permissions or enable a public service unrelated to this project.
6. Geant4/remage provides radiation deposits, positions, creation times and identities. SSD provides semiconductor drift and electrode signals. Readout is a separate stage. A deposition time is not a drift time.
7. Keep all relevant deposits of one event grouped. Keep truth Edep separate from readout-derived Erec. Do not set the energy gain separately for each event.
8. Reuse existing SSD, ParaView and remage functionality. Do not introduce a second frontend framework, Docker, a VM or another solver solely to publish static results.
9. Record exact software versions and random seeds. Distinguish smoke tests, numerical convergence, and agreement with experiment.
10. Before committing: validate relevant outputs, inspect the diff, update PROGRESS.md in place, and commit a meaningful milestone. A documentation-only edit does not require rerunning physics or regenerating unchanged results. Push without force; stop for conflicts.

## Keep active context short

PROGRESS.md is the single current handoff; its immutable-history link preserves the full prior log. Do not append another full round transcript. Read debug output by bounded ranges and exact fields. Write long evidence to local files, not repeated terminal/chat dumps. Close owned idle sessions after each round; never clear global shell history, chat records, authentication stores or scientific evidence. Use only directly relevant developer checks; no additional reviewers.

## Publication and onboarding ownership

Keep README as a short browse/run entry. The maintained Windows setup authority is tools/site_guide.html; advanced component READMEs are not competing beginner routes. Use tools/MAINTENANCE.md for source ownership. Normal Publish.cmd preserves the checked saved snapshot and refreshes maintained navigation/viewer HTML without physics. Derive presentation eligibility from scenarios/detector-capabilities.json while keeping independent backend checks. Seventeen viewable models do not imply seventeen LBNL-executable models.

Owner update (2026-10-07): prioritize student use of compatible catalog models
through one shared model-data and computation workflow. Reuse existing common
functions; do not make a bespoke adapter, hours of development, or a separate
full review for every model a prerequisite. Report concrete compatibility limits
and missing inputs. Do not enable a model from its label alone or silently change
the selected cryostat. The temporary batch-UI pause ended after this model-coverage
delivery and the owner's subsequent approval: M15b/M15c are now accepted at
e489faf. Preserved WIP in .local/student-batches-v1/wip/ is historical evidence;
the current PROGRESS.md handoff governs further bounded work.

Real browser acceptance must not click Download or trigger Save As, and must not
change the owner's browser settings. Verify downloads through protected HTTP and
mock/source contracts. Resource-bounded independent calculations may run in
parallel when useful, retaining distinct seeds, roots and provenance; measure
available memory first and avoid memory oversubscription or parallel field solves
when the machine has insufficient headroom.

## Existing tools

- `tools/build_site.py`: deterministic export of the locally generated library into docs/.
- `tools/export_models.py`: explicit `--import` of recorded originals; portable `--validate` of versioned snapshots. Site model downloads use `models/` only. Unexpected managed edits must fail, never be overwritten.
- `tools/smoke_test.jl`: bounded AK01 event replay in the existing Julia environment.
- `tools/smoke_scene.py`: existing AK01/GeGI native-state reload and render.
- `tools/migrate_paths.py`: explicit old-root replacement with an originals ZIP; do not rerun blindly.
- `Publish.cmd`: approved publication workflow. Browser authorization may require the owner.

Do not claim that Work/Codex has been started merely because these instructions exist. The execution environment and actual working directory must be verified in that session.

## Work/Codex model preference

Owner update (2026-09-30): use `gpt-6.1-sol` with `model_reasoning_effort="ultra"`
for this project's development/review agents. This supersedes the earlier Astra-only
policy; prior receipts remain historical facts. Verify model/effort and working
root on every launch; never silently substitute a model or weaker setting.
Do not change global user configuration, install another environment, enable Fast
or separately billed APIs, or consume reset/banked reset credits. Only the owner
may use reset credits. Keep all task files in the existing project/evidence root.

Owner update (2026-10-07): remove M8/M9 second-computer acceptance from the active
delivery plan. Improve the maintained setup/use route from actual student feedback;
do not wait for another computer or claim unperformed installation validation.
Do not run installation experiments, create novice environments or alter
system PATH/WSL/global packages on the current machine. Keep tracked local code,
configuration and lockfiles synchronized with GitHub; retain machine-specific
paths, private inputs, caches and raw scientific outputs locally and identified.

## Publication validation

Run tools/test_site.py and tools/check_site.py before publishing. Build only through tools/build_site.py; never hand-edit docs/. Verify the live build with tools/check_site.py --url after deployment, rather than relying on the publisher's basic reachability message. Keep the public manifest and exact-byte Git attributes intact. The original numerical workspace remains out of scope for a publication-only edit.

## Portable CPU example

M1a includes only the reviewed simulation/Project.toml, Manifest.toml, run.jl and README.md. Keep this environment separate from the preserved full campaign. Run --check-models and the bounded cache-free example before changing the lockfile or runner; log any differences. Generated files belong under .local/, not models/, simulation/ or docs/. The canonical model snapshots are deliberately frozen by reviewed hashes; do not silently mutate them.

## M1b compute and transport boundaries

Use the shared simulation/run.jl for both CPU and optional CUDA. CPU remains installable without CUDA. Never silently fall back from a requested GPU or force partial charge to unity. Report potential-solve and end-to-end times separately; warm-up is not production timing. Before upgrades run parser/model tests, CPU regression and the explicit parity benchmark. Do not loosen comparison gates to force a pass.

transport/ keeps the Pixi manifest/lock and toy installation checks; large environments belong to Pixi’s detached Linux cache. Preserve cryostat-source.json provenance and locally cached upstream bytes. No LBNL geometry or drift/recombination validation may be inferred from the toy Ge-box smoke test. Keep coupling pending until geometry/units/event mapping are independently checked.

## M2 scientific scope

AK02 (Anupama ICPC2) is the Li-contact primary case; SAP22 is a non-Li cross-check, not a matched-geometry experimental control. Defer new GeGI work. Preserve original 78 K / +500 V and +700 V snapshots; first reproduce them, with any nominal 77 K override explicit and consistently recorded. No invented experimental holder/source positions or uncalibrated lifetime claims.
Read-only research elsewhere under My Drive is authorized; never edit unrelated files. Keep raw transport energy separate from charge response; no double Li loss. Preserve event IDs, deposition times, transforms, zero-deposit primaries and incomplete-collection flags.
After bounded implementation/testing, perform only directly relevant developer
checks and record actual limitations. The 2026-10-14 owner correction prohibits
extra AI reviewers and peer-review rounds; older reviewer receipts are history.

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

## Explicit native-failure accounting

Long campaigns may explicitly select `--native-failure-policy record`; default
`abort` and the original native helper remain strict. Only the two documented
native-domain ArgumentErrors may be isolated. Unexpected exceptions still abort.
A failed group retains its complete truth/identity ledger and exact error; unknown
charge, endpoint and readout quantities remain null, never zero or a fabricated
waveform. Count native failures separately from electronics rejections and preserve
`completed_with_native_failures`. This is processing completion, not validated
transport. Diagnose a concrete failing event separately; do not rectify signals,
relax geometry checks, retune seeds or promote global Li research into an unrelated
functional-delivery gate. A large run still requires a clean, verified pilot.

## Interruption recovery: never confuse chat failure with computation failure

After Thinking failed or a disconnected chat, first inspect Git, final run.json,
recorded source hashes, actual process identities and the owned supervisor lock.
A terminal completed/completed_with_native_failures receipt takes precedence over
a stale running handoff. Reconcile state and export existing artifacts; do not
repeat completed physics, pilots, reviews or agents solely to recover a reply.
Reuse prior review findings. New agents require a substantive new implementation
or a specific unresolved question, not rediscovery of already recorded results.
Keep usage summaries local and distinguish cached CLI token telemetry from billed
quota percentages. Preserve raw results, failed attempts and all original modes.

## Freeze writers before saved-data export

Before launching any hash-bound export, wait for its implementation writer to
exit and record source hashes. A changed-source failure is an incomplete derived
bundle, not a reason to repeat Geant4 or SSD. Preserve failed derivative evidence;
retry only the exporter after source freeze. Radiation STEP chords and Track birth
records must not be labeled complete trajectories across unscored material.

## Owner-approved standalone million-decay transport

The owner approved1M initial Cs137 decays per detector with the existing default
uncollimated source and accepted geometry. This is Geant4 only, independent of
unresolved native Li/cap questions. Use tools/long_transport.py and its detached
launcher; preserve all old10k science files. Verify/resume DONE chunks, never
restart completed radiation solely because the chat or workstation interrupted.
Compact HDF5 and lossless raw archives preserve future analysis without radiation
reruns. Do not launch SSD/readout or continuously invoke agents while transport
runs. Local progress files and final COMPLETE.json are the execution authority.

## Completed campaign retention (owner request, 2026-09-27)

`.local/cs137-1m/` and its original archives, compact HDF5, configuration, inputs,
DONE and COMPLETE records are permanent science data, not disposable cache.
See tools/DATA_RETENTION.md. No automatic cleanup or radiation rerun is authorized
for postprocessing. Use new derivative folders and preserve old10k baselines.
