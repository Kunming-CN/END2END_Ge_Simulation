# Next development plan

Updated: 2026-10-10 (owner client date). This is the single active delivery roadmap.
[Onboarding and extension contracts](ONBOARDING_EXTENSIBILITY_PLAN.md) retain the
longer-lived boundaries; [PROGRESS.md](../PROGRESS.md) records actual delivery.
This revision is planning only, for the owner's next evaluation. It does not start
implementation, simulations, publication or an automatic continuation schedule.

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
| Local Control / ten compatible configurations | Shared engines, admitted Cs137/Am241/Ba133, exact counts, serial batches, stage-boundary Stop/Resume and lazy saved analysis are delivered. This is not thirty independently run physical validations. |
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

## One next implementation milestone: source/capsule angle

**User outcome:** select an admitted radioactive source, compatible detector and
angle in Control; Check plan shows the effective pose, Run uses that same pose,
and saved results preserve it. The cryostat and detector mounting stay fixed.

**Inputs:** scenarios/placement-anchors.json, source-presets.json, the current
cryostat, detector capability/model descriptors, existing shared exporters,
CLI/Control configuration, batch execution and stage validators. Existing saved
contracts are fixed-position; introduce an explicit supported pose/version for
new runs rather than rebasing old receipts or loosening their validators.

**Nominal geometry:** global-z axis at x=0/y=1.473 mm, outer radius 35.1 mm,
source-centre radius 35.6 mm and z=0.290 mm. Degrees from +y toward +x:
`p(theta)=[35.6*sin(theta), 1.473+35.6*cos(theta), 0.290] mm`.
Capsule/fill use separate `Rz(-theta)*Rx(-90 deg)` placement; never rotate the
crystal/spacer through the existing shared rotation. This is engineering geometry,
not a measured source survey or an experimental efficiency claim.

### 1. Resolve one shared pose

Add the smallest angle/pose resolver using the recorded anchor, units and rotation
convention. Detector selection, source identity and pose remain independent.
Angle zero must produce the exact nominal position and original physical setup;
legacy Gamma keeps its fixed 20-primary/+5 mm position and -y direction.

Output: one resolved source/capsule/fill pose and explicit capability/version,
consumed by preparation, macro generation, configuration and provenance. Establish
safe angle support against actual solids/placements before advertising a range.
Containment/overlap failures must be refused before transport, with a clear reason.
No arbitrary uploads, axial translation, capsule material editing or new cryostat.

### 2. Wire the existing CLI and Control

Add one degree-valued angle field, zero default, and a readable position/orientation
preview from the same resolved inputs. Preserve chosen detector/source/angle through
Check, Run, Stop/Resume and reopening results. Ordinary use requires no source or
configuration editing. Add only the guide/help text this new control needs.

Output: shared CLI/GUI effective configuration and source macro; saved results show
angle, position, coordinate convention and provenance. Existing fixed-pose jobs stay
readable/resumable. A changed physical pose requires new transport; do not relabel
an old run. Fields/charge/calibration reuse requires the existing strict applicable
contracts, not merely an unchanged detector name. No per-model bespoke adapter.

### 3. Validate geometry, identity and controls before one calculation

Focused checks cover theta=0 and both signs of representative nonzero angles,
source inside fill, tangent radial placement, capsule/fill rotation, unchanged
cryostat/crystal/spacer/material/contact/readout, GPS vertex and source identity.
Compare checked inputs with actual exported native geometry/macro, including the
existing independent overlap checks; a pretty preview is not acceptance.

Use software/geometry checks for the shared route and admitted model/source
choices; do not run thirty physical combinations. Check CLI/Control parity,
invalid angle/refusal, pose-sensitive reuse, saved input inspection and recovery
binding. Browser checks cover this new control and affected previews/results only;
never click Download/Save As or change browser settings.

### 4. Run one bounded nonzero-angle acceptance and deliver

Predeclare one SAP22/Cs137 case at +30 degrees, 500 initial nuclei, seed 26092631,
in one new owned output root, after geometry checks. Maximum: one new 500-nucleus
transport trial; compute native charge only for its actual eligible pulse groups.
Use existing preparation/cache where its verified bindings allow; at most one
necessary native field preparation. Keep all initial identities, zero primaries,
multiple groups, delays, caps, signed/null signals and readout rejection records.
Independent injection calibration and truth Edep/readout Erec stay distinct.

Acceptance requires a completed traceable new-pose run with at least one genuine
positive accepted full-chain signal, exact input/placement identity and event census,
plus the focused tests and actual Control/CLI behavior above. If the fixed case has
no accepted positive signal or fails, retain that outcome and report the concrete
reason; do not repeat with different seeds/counts/gain or disguise it as a pass.
Any further science would need a separately justified bounded plan.

Stop after one integrated tested milestone, the required two scoped AI reviews and
NEW independent direction/details review, fixes for verified blockers, relevant
checks, synchronized Git and owned worker/lease closure. Re-review only specific
corrections. Run the site build/local/live checks only if public site output actually
changes. No second source/model campaign is required to finish this feature.

## Conditional work after or alongside that milestone

These are options or response policies, not mandatory stages to complete first.

| Trigger | Small useful action | Acceptance and stop |
|---|---|---|
| Real student cannot set up, run, stop/resume or find data | Reproduce the specific blocker through the existing dependency check, Control and guide; use saved cases first. A true core blocker takes priority over a new feature. | Verified fix for that report; no speculative setup rewrite, new environment or second-PC gate. |
| An affected page/control or a new concrete display defect | Reuse existing exact-bin, selected-identity, expected-model, original-byte and route tests. The SAP22-removal/rehash regression already exists. Add only a missing regression tied to the defect; inspect affected plots on desktop/narrow layout and live after publishing. | Correct display with data/units/populations unchanged, no repeated 105-page or physics campaign. |
| Owner wants another common isotope after the angle feature | First do a read-only Co60 admission assessment from its retained trial: distinguish valid below-threshold event rejection from source/timing/processing invalidity. Existing zero-rejection admission remains unchanged during assessment. | Evidence-based adopt/keep/defer recommendation. Gate changes or a new calculation are a separate reviewed decision, never a retry until pass. |
| Measured run/UI delay blocks actual use | Profile the slow stage and use existing preparation/lazy access before changing concurrency. Parallel independent runs only with measured memory headroom, separate roots/seeds and no competing writers. | Measured improvement without provenance/numeric changes; no promised speedup or parallel field solves without headroom. |

## Removed prerequisites and deferred research

- Remove a new M10 prototype, generic M5b, mandatory new-cryostat M11 demonstration,
  repeated website reorganizations and duplicate analysis/help systems from delivery.
  These were complete, inappropriate for this cryostat, or lacked a concrete need.
- Seven oversized detectors require a future larger cryostat with real dimensions,
  materials and mappings; never shrink them or change the selected world silently.
- M3 experimental preamp/ORTEC/noise, Li/depletion/transition accuracy, measured
  calibration and deeper GeRC work remain separate research lanes. The owner's
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
