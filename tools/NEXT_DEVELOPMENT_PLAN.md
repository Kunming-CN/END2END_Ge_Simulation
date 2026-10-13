# Next development plan

Updated: 2026-10-13. This is the single active delivery roadmap.
[Onboarding and extension contracts](ONBOARDING_EXTENSIBILITY_PLAN.md) retain the
longer-lived boundaries; [PROGRESS.md](../PROGRESS.md) records actual delivery.
The source-angle feature is delivered through shared Check/Run. Co60 admission
now reuses its audited saved threshold rejection, with original failures retained.
Student software ZIPs exclude the retained website showcase directory.
Owner authorization, 2026-10-13: continue the executable development below
without reminders or per-round approval, with automatic continuation in this
chat. Complete one bounded, tested milestone at a time in audit-priority order,
then the desktop improvements and PSD1/PSD2/PSD3. Reuse saved science; this does
not authorize another radiation/field campaign, installations or missing-input
experimental claims. Conditional work remains conditional.

Owner clarification, 2026-10-13: this software is for desktop computers.
Develop and accept the local application and its supporting website for desktop
use, including keyboard/mouse operation, readable plots and desktop window sizes.
Mobile adaptation and phone acceptance are out of scope. Earlier320/390px audit
observations remain historical evidence, not an active improvement queue or gate.

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
| An affected page/control or a new concrete display defect | Reuse existing exact-bin, selected-identity, expected-model, original-byte and route tests. The SAP22-removal/rehash regression already exists. Add only a missing regression tied to the defect; inspect affected plots in desktop windows and live after publishing. | Correct display with data/units/populations unchanged, no repeated 105-page or physics campaign. |
| Owner requests another isotope | Reuse the shared source assets and inspect a bounded trial's identity/timing/energy and processing evidence. Co60 is already admitted through pinned below-threshold evidence; do not repeat its original calculation. | Retain rejected events and strict native/saturation/provenance checks. No seed/threshold retuning or retry-until-pass policy. |
| Measured run/UI delay blocks actual use | Profile the slow stage and use existing preparation/lazy access before changing concurrency. Parallel independent runs only with measured memory headroom, separate roots/seeds and no competing writers. | Measured improvement without provenance/numeric changes; no promised speedup or parallel field solves without headroom. |

## Deferred to November 2026: publish real laboratory measurements

Owner addition, 2026-10-10: the laboratory has further detectors, and both those
and the detectors already represented on GitHub have measured energy spectra,
I-V and C-V data. Add public student access after the owner supplies the complete
measurement files/metadata. Earliest execution: next month (November 2026); this
entry remains deferred until November and complete owner inputs. The authorized
continuation may then implement the agreed publication if both conditions hold.
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
original-file access and desktop/live display through existing publication
checks. Then register further complete datasets through that same template, with
only their data/metadata checks, not new code/adapters/reviews per specimen. Stop
at readable, traceable publication of the supplied agreed batch. No new Geant4/SSD
run, forced simulation overlay, global parameter fit or waveform/experimental
agreement claim is required. Any later comparison/calibration study is separate.
Until November and complete inputs arrive, retain this item as deferred.

## Owner-approved plan: pulse-shape analysis before machine learning

Owner addition, 2026-10-13, inspired by Yuan-Ru "Leon" Lin's APS DNP presentation,
*Supervised Learning Engine for Energy and Pulse-shape* (2026-10-13, slides13-24).
The useful direction is a reproducible waveform/feature workflow with an A/E
baseline, followed by a bounded classifier comparison. Slide16 reports about9%
multi-site survival at90% single-site acceptance for both the real-data classifier
and production A/E; slides17/24 describe simulation-trained classification as
future work. Do not cite this presentation as proof of a simulation-training gain.
The private presentation is a reference, not a public repository input.

**User outcome:** a student traces one event from deposition topology through
signed charge/current and electronics to reproducible pulse-shape features,
then compares event selections without losing the original event census.
Keep the existing remage/SSD/readout engines, Control and saved-analysis route.
Real student blockers take priority, and November measurement publication remains
independent. Implement one complete stage at a time; do not make machine learning
or global Li/PDE/CCE research a prerequisite for the first engineering example.

| Stage | Concrete inputs and outputs | Necessary acceptance and stop |
|---|---|---|
| PSD1: saved-waveform features | One completed small case with full-resolution signed charge data, stable event/deposit identities, endpoint flags, exact electronics/calibration and source hashes. Produce a shared feature export and existing-viewer access to A/E, rise time and linked topology. | Independently recompute selected features with recorded units, polarity, filter, alignment and crossing definitions; preserve every event and selection reason. Stop at one traceable teaching/engineering case. No new radiation/field solve or all-model campaign. |
| PSD2: explicit waveform acquisition | After PSD1 acceptance, add a separate versioned waveform-acquisition profile with sampling rate, ADC range/bits, record/trigger window, bandwidth and explicit noise assumptions/seeds. Consume full-resolution signals, with independent injection calibration. | Verify sampling, time origin, clipping/window flags, charge/energy response and uncertainty with bounded injections. Preserve frozen peak-ADC regression and current preamp display. Stop at one reproducible synthetic acquisition example; do not claim a measured hardware model. |
| PSD3: bounded classifier comparison | After usable waveform export and explicit label/split contracts, compare A/E with a small autoencoder plus classifier. Retain dataset/model/preprocessing hashes and all selection/split records. | On an independent test set compare background survival at the same signal acceptance, with sample counts and uncertainty. Keep variants of one original event in one split; fit preprocessing/calibration only on permitted training/calibration data. Stop at the measured comparison, whether or not machine learning improves it. Real-data performance requires actual recorded waveforms. |

**Feature and label integrity:** define A as a declared filtered current-peak
observable and E as independently calibrated reconstructed energy; keep truth
Edep separately. Specify signed electrode/polarity convention rather than silently
rectifying pulses. Zero/invalid energies, native failures, incomplete endpoints,
threshold rejection and saturation retain explicit status and null unavailable
features. Display traces are bounded/downsampled and must not be used as the
full-resolution feature or training input. A native parcel fluctuation is numerical
sampling, not physical noise or measured resolution.

Single-site/multi-site truth requires a recorded spatial clustering rule and
sensitivity check, not a Geant4 step/deposit count. Calibration peak selections
are labelled proxies with contamination limits, not perfect truth. An A/E-derived
label or training selection cannot independently demonstrate superiority to A/E;
retain such selection and possible bias explicitly. Additional isotope/source
admission is separate work, not silently bundled into PSD1.

Before PSD3, declare the evaluation population, sample adequacy and inconclusive
result rule. Choose architecture/hyperparameters and selection thresholds using
training/validation or separate calibration data; inspect the final held-out test
only for the declared evaluation, without tuning to its result. A seven-pulse
engineering example establishes the feature workflow, not classifier performance.

**Current input limits:** existing readout is analog preamp/shaping followed by a
single peak ADC code, not waveform digitization. The original AK02/SAP22 measured
pulse waveforms were not saved; energy spectra alone cannot validate pulse-shape
classification. PSD1 may use a clearly labelled saved engineering example despite
unresolved physical accuracy gates. PSD2/PSD3 remain later stages. The owner's
subsequent continuation authorization covers their bounded implementation and
acceptance in order; no installation, backend migration or new radiation/field
campaign is included.

## Software audit priorities: owner request, 2026-10-13

The owner requested an adversarial audit, evidence-based software defence and
importance-ranked improvements, explicitly including the interface. Three new
Sol6.1/Ultra AI agents ran independent initial reviews, then exchanged concrete
findings; a new third reviewer adjudicated details and direction. Root inspected
the actual public site and protected local Control in Chrome, including keyboard
focus and historical390px Control/320px public-page observations. The owner has
removed phone adaptation/acceptance from subsequent work. Source/mock checks and retained
artifacts support the audit; it is not exhaustive correctness, security, fresh
installation, experimental or numerical-convergence certification.

Coverage included source/geometry/units/timing, native charge/endpoints/failures,
electronics/calibration/ADC, event census/provenance, source/model admission,
Stop/Resume/process ownership, setup/archive/portability, saved publication,
interface/navigation/accessibility, resources/tests and maintenance complexity.
No radiation, field, drift or electronics calculation was repeated. No Run,
Download or Save As was clicked. The initial audit itself changed no application implementation; subsequent delivery is recorded in PROGRESS.md.
Private evidence is retained in `.local/software-audit-v1/`; original science and
public saved numerical/media/model files remain unchanged.

| Order | Confirmed issue and evidence | Small useful correction and necessary acceptance |
|---|---|---|
| Delivered / STRICT-01 | Proven pre-Popen preparation failures now have an explicit supported recovery; old opaque/Popen-entered failures stay blocked. | Shared journal/lease/persistent reread and CLI name reservation preserve original evidence. Failed Resume needs the original sealed checkpoint; later CLI completion/new stop is settled by explicit Verify and a checked control authority. Initial159 regressions, overlapping72/45 correction runs, Node contracts, desktop fixture acceptance and three independent AI targeted rechecks passed. See current PROGRESS.md and `.local/strict01-recovery-v1/COMPLETE.json`. |
| Delivered / STRICT-02 | New Am241/Ba133/Co60 JSON schema2/descriptor1 and CSV use the selected source's closed diagnostic windows and `per_emitted_diagnostic_window_photon`. Historical aliases/bytes and Cs137/gamma contracts remain. | Shared export/merge and actual validators check source/window/CSV semantics and truth-derived named counts. Catalog accounting, active-validator wiring and report-only version downgrade findings were corrected. Initial47 Python/84 actual exporter checks; affected10/7 overlapping Python runs,61 actual catalog checks,7 cross-language views and three scoped AI final rechecks passed. Reuse `.local/strict02-normalization-v1/COMPLETE.json`; no physics rerun. |
| 3 / P2 / STRICT-03 | Every2.5s poll replaces run/recovery controls even for unchanged state. Actual Chrome keyboard focus changed from Show stages to BODY without other page input. | Keep stable keyed controls or skip unchanged renders; preserve focus/caret and pending-action state when replacement is necessary. Check two unchanged polls, meaningful status changes, keyboard activation and stale-selection guards. No duplicated science or wrong-event result was demonstrated. |
| 4 / P2 / UI-PRIMARY-CONTRAST | Enabled primary-button CSS uses ordinary16px white text on `#008a96`, contrast4.137284:1. The observed disabled button is exempt and is not the claimed failure. | Adjust only the enabled UI foreground/background to meet ordinary-text4.5:1; retain visible focus, disabled distinction and categorical detector colors. Check computed enabled styling and a focused real-browser view. See [W3C contrast criterion](https://www.w3.org/TR/WCAG22/#contrast-minimum). |
| 5 / P3 / UI-ANGLE-READINESS | Check environment still labels the angular exporter "preview; execution pending" while its note and current capability state correctly allow angular execution after Check. | Use neutral file-readiness wording or one flag-derived status. Check accepted/pending source states and preserve backend admission; this is stale wording, not an angular-geometry failure. |

**Desktop interface improvements after core fixes:** improve visible blocking
reasons and specific next actions, keep the selected run and effective settings
clear, and add recorded pulse/status hints or an explicit signal-finding filter
to bare numeric primary options while retaining the full census. Assess plot
readability and action placement in actual desktop windows; do not transfer the
earlier phone-width measurements into desktop defect claims. Keep the existing
frontend and retained scientific limits. Phone layout/axes/form-density work is
removed from the active plan; its audit records remain historical.

**Later conditional engineering gaps:** add measured resource/storage preflight
when a real run requires it; preserve lazy serial batching. A small portable
regression/CI tier would help maintain the growing source-bound legacy surface;
it is not another installation/physics campaign. Resolve actual student setup
feedback through the existing guide. Physical CCE/noise/experimental agreement,
missing measured waveforms and independent off-device backup verification remain
declared limits, not newly proven software defects or prerequisites for PSD1.

STRICT-01 and STRICT-02 are delivered; the next bounded implementation is
STRICT-03. The initial audit remains historical evidence. Authorized automatic
continuation implements the remaining ranked desktop corrections and then PSD
stages; review only verified corrections or newly affected risks, without
repeating the full audit or completed science.

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

Automatic heartbeat is ACTIVE; this STRICT-02 round received its actual trigger
on2026-10-13. Subsequent work starts from current PROGRESS, actual Git/remote/
processes, terminal receipts and the owned lease; never replay completed work
after a chat failure. Existing publication/capability checks remain mandatory
where applicable. Stop extending scope when all executable authorized work is
complete; retain missing-input and physical-validation conditions explicitly.
