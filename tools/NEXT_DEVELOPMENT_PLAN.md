# Next development plan

Updated: 2026-10-11. This is the single active delivery roadmap.
[Onboarding and extension contracts](ONBOARDING_EXTENSIBILITY_PLAN.md) retain the
longer-lived boundaries; [PROGRESS.md](../PROGRESS.md) records actual delivery.
The source-angle feature is delivered through shared Check/Run. Co60 admission
now reuses its audited saved threshold rejection, with original failures retained.
Student software ZIPs exclude the retained website showcase directory.
No further science campaign or automatic continuation is queued.

## Outcome and verified starting point

A student selects a compatible detector and admitted source in the existing
cryostat, runs one end-to-end job through Control, and traces any saved stage.
Keep the pinned remage 1.1.0/Geant4 11.3.2, SSD 0.11.8 and separate readout
engines. Keep one world,
shared detector/source assets and resolved placements; do not store a manually
maintained configuration/geometry copy for every combination. A run must still
save its exact effective inputs and source/model/software hashes for analysis.

| Delivered or disposed scope | Evidence and limit; remove from new-work queue |
|---|---|
| M4 / bounded M5 recovery | Closed; original success and failed attempts remain separate. No general M5b prerequisite. |
| Optional M6 interface pilot | Existing installed readers retained; unavailable reboost/simflow deferred. No installation or backend migration. |
| Local Control / ten compatible configurations | Shared engines, admitted Cs137/Am241/Ba133/Co60, exact counts, serial batches, stage-boundary Stop/Resume and lazy saved analysis are delivered. Forty factorized source/model choices are not forty independently run physical validations. |
| Student software download | GitHub source ZIP excludes docs/ while Pages retains showcase files. Full clone/history still includes website data; dependencies/upstream inputs require documented setup. Final archive/live checks are recorded in the current COMPLETE.json. |
| Larger detector models | Seven viewable models do not fit this cryostat; future larger-cryostat work, not adapters to finish now. |
| Analysis and beginner route | Raw radiation, ledger, signed charge, readout, calibration/settings and stable identities are accessible; README is a short entry and tools/site_guide.html is the one setup authority. |
| Saved plots, teaching and navigation | Accepted saved-data/site work; six representative later Cs137 examples replace the old teaching default. Preamp behavior remains unchanged. Existing reports/URLs/full event ledgers remain accessible. |
| Both-detector million overview | AK02 and SAP22 shown together; SAP22 data were never deleted. Accepted at 7259bf7 with actual browser/live checks. |
| Second-computer acceptance | Removed by owner; act on real student feedback without claiming unperformed fresh installation. |

Website evidence includes the accepted earlier 105-page/64-direct-SVG audit and
retained 490-image/172-inline-chart coverage, then the six-example 24-plot checks,
and the latest two-model correction with 703 exact live files. These scopes are
not a fresh physics validation of every image. Reuse completed evidence; do not
queue another full-site audit without a concrete change or defect.

## Source/capsule-angle milestone: delivered, stop condition met

**User outcome:** select an admitted radioactive source, compatible detector and
angle in Control; Check resolves the effective pose and enables Run through the
shared CLI/backend. New saved artifacts retain that pose, all primary IDs and
original stage provenance. The cryostat and detector mounting stay fixed.

The shared resolver, capsule-only native exporter and +/-30deg geometry checks
were accepted in the prior milestone. Zero and legacy Gamma keep their original
macros/admission. Ten compatible descriptors share the engineering route; neither
seventeen viewable models nor forty source/model choices are physical validations.
Nominal engineering pose remains
`p(theta)=[35.6*sin(theta), 1.473+35.6*cos(theta), 0.290] mm`, with degrees from +y
toward +x around global z at x=0/y=1.473mm and fixed crystal/spacer/materials.

The new precise-GPS adapter uses /control/useDoublePrecision true immediately
before the angular centre. Its native command-only test reproduces the earlier
4.374726nm error, then passes three poses with zero difference and unchanged
1e-10mm identity tolerance, generating no events. Original failed data stay
immutable; their already simulated trajectories were never repaired or relabelled.

One new fixed SAP22/Cs137/+30deg/500/seed26092631 acceptance completed one field
preparation and one radiation trial. It retained493 zero-deposit primaries and
accepted seven positive pulse groups with zero native failures/readout rejections/
saturation. Bias, temperature, native physics, electronics and independent injection
calibration stayed fixed; only the run name changed. No trial or campaign retry
is queued. This is functional engineering acceptance, not experimental angular
efficiency, calibrated CCE, physical resolution or global numerical convergence.

Focused tests and three required independent AI reviews passed. Real Control
Check/Run availability was verified without another browser science launch; the
new saved case was inspected through the existing backend, not fabricated as a
GUI history record. See PROGRESS.md and .local/source-angle-precision-v1/COMPLETE.json
for exact final evidence, publication, Git and owned session/lease closure.
The milestone stop condition is met; next work requires a concrete trigger below.

## Conditional work after the delivered milestone

These are options or response policies, not mandatory stages to complete first.

| Trigger | Small useful action | Acceptance and stop |
|---|---|---|
| Real student cannot set up, run, stop/resume or find data | Reproduce the specific blocker through the existing dependency check, Control and guide; use saved cases first. A true core blocker takes priority over a new feature. | Verified fix for that report; no speculative setup rewrite, new environment or second-PC gate. |
| An affected page/control or a new concrete display defect | Reuse existing exact-bin, selected-identity, expected-model, original-byte and route tests. The SAP22-removal/rehash regression already exists. Add only a missing regression tied to the defect; inspect affected plots on desktop/narrow layout and live after publishing. | Correct display with data/units/populations unchanged, no repeated 105-page or physics campaign. |
| Owner requests another isotope | Reuse the shared source assets and inspect a bounded trial's identity/timing/energy and processing evidence. Co60 is already admitted through pinned below-threshold evidence; do not repeat its original calculation. | Retain rejected events and strict native/saturation/provenance checks. No seed/threshold retuning or retry-until-pass policy. |
| Measured run/UI delay blocks actual use | Profile the slow stage and use existing preparation/lazy access before changing concurrency. Parallel independent runs only with measured memory headroom, separate roots/seeds and no competing writers. | Measured improvement without provenance/numeric changes; no promised speedup or parallel field solves without headroom. |

## Deferred to November 2026: publish real laboratory measurements

Owner addition, 2026-10-10: the laboratory has further detectors, and both those
and the detectors already represented on GitHub have measured energy spectra,
I-V and C-V data. Add public student access after the owner supplies the complete
measurement files/metadata. Earliest execution: next month (November 2026); this
entry schedules no automatic work and does not start implementation/publication.
It is independent of source-angle delivery and of any new cryostat/solver admission.

**Outcome:** students can find a real detector's measured spectrum, I-V and C-V
curves, inspect measurement conditions and access the published original data.
Reuse the current detector overview/Results routes and one shared dataset template;
do not create another website, competing entrance or bespoke page per detector.
A measurement-only laboratory detector can have a public record without claiming
its geometry is already an executable simulation model.

**Inputs after delivery by owner:** original numerical files and available original
plots, a stable physical-detector identity, measurement date/provenance, units and
measurement conditions. Map physical specimens to existing catalog models only
when that relationship is confirmed; do not infer identity from similar names.
For spectra record channel/energy calibration, acquisition/live time where known,
source/placement, bias/temperature/readout and background/subtraction status.
For I-V retain signed bias/current, units, temperature and sweep conditions; for
C-V retain bias/capacitance, units, temperature, test frequency and AC amplitude.
Preserve supplied uncertainty/calibration records; missing information is labelled
unknown, not invented or treated as experimentally validated. Public inputs are the
owner-provided releasable measurements/metadata, excluding unrelated private files.

**Output:** one versioned measurement record per physical detector/campaign, with
original file hashes, conditions, numerical data links and checked plots. Keep
measured data visibly distinct from simulated/derived results. Background removal,
normalization, calibration or other processing has explicit inputs/method/version
and retains the original data. Do not silently alter curves or retune simulation.

**First acceptance and stop:** begin with one complete detector dataset containing
all three measurements; check plotted numbers/axis units, identity, conditions,
original-file access and desktop/narrow/live display through existing publication
checks. Then register further complete datasets through that same template, with
only their data/metadata checks, not new code/adapters/reviews per specimen. Stop
at readable, traceable publication of the supplied agreed batch. No new Geant4/SSD
run, forced simulation overlay, global parameter fit or waveform/experimental
agreement claim is required. Any later comparison/calibration study is separate.
Until November and complete inputs arrive, retain this item as deferred.

## Removed prerequisites and deferred research

- Remove a new M10 prototype, generic M5b, mandatory new-cryostat M11 demonstration,
  repeated website reorganizations and duplicate analysis/help systems from delivery.
  These were complete, inappropriate for this cryostat, or lacked a concrete need.
- Seven oversized detectors require a future larger cryostat with real dimensions,
  materials and mappings; never shrink them or change the selected world silently.
- M3 experimental preamp/ORTEC/noise, Li/depletion/transition accuracy, experimental
  calibration fitting and deeper GeRC work remain separate research lanes. The owner's
  current preamp-display instruction is to leave it unchanged.
- No new million campaign, all-combination transport/SSD campaign, installation,
  backend/framework migration, global PATH/WSL/package change or reset credits.

## Working and maintenance rules

Use one existing project/environment and meaningful run outputs, not duplicate
reports or speculative scaffolding. State concrete inputs, outputs, acceptance,
compute bounds and stop before each implementation. Preserve unique failures,
scientific inputs and original source bindings. Measure science separately from
coding/review/publication time; do not invent an ETA.

Automatic heartbeat remains PAUSED. This revision only updates the plan for owner
assessment. Later work starts from current PROGRESS, actual Git/remote/processes,
terminal receipts and the owned lease; never replay completed work after a chat
failure. Existing publication/capability checks remain mandatory where applicable.
