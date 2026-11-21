# GeSignal development plan

The student workflow runs from detector and source selection through transport, drift, electronics and event analysis. Current development targets what the digital signals in GeGI can establish about interaction position. The [handoff](../PROGRESS.md) records delivered versions, numerical checks and saved inputs.

| GeGI stage | Status and scope |
|---|---|
| 1. Electrode signals | Saved complete signed traces cover 32 strips and two guards, including transient charge on noncollecting neighbors. |
| 2. Fast and slow readout | Fresh continuous acquisition and saved replay use the same nominal digitized preamplifier readout. The fast branch measures signed area, the slow branch measures pulse energy and collecting-strip timing supplies a depth observable. |
| 3. Single-site position | Four directly calibrated strip pairs, lateral transfer on nine additional pairs, and apparent-depth timing curves across 216 pixels. Control shows evidence and availability per estimate. |
| 4. Two-site reconstruction | All 3,822 eligible two-strip candidates were processed from the completed five-second archive; 11,087 remain outside that original fit scope. Optional shared-strip companion imaging is now connected to CLI/Control, with two selected shared candidates accepted. Its 4,410-candidate input census is not a completed full refit. |
| 5. Experimental comparison | The 32-channel simulated spectrum export is available. Matching the instrument selection, pixel map and spectra requires a common acquisition and its metadata. |

## Delivery order

**Active reconstruction development, November 21:** the owner has resumed work
after the completed readiness delivery. The current-thread `gegi` heartbeat runs
every 30 minutes. This supersedes the completed-readiness pause below for this
development scope. The five-second archive is the development baseline; new
independent inputs establish generalization after selection/model choices settle.

| Delivery | Implementation and acceptance |
|---|---|
| 1. Edge-peak attribution | Delivered. Reuse the three-window contributions and exact dominant histories to choose physical hypotheses; do not repeat event archaeology as a delivery prerequisite. |
| 2. Native response repair | Cause-specific repairs and the 1,971-group reconciliation are delivered. Connect accepted numerics and configurable support to new normal acquisitions, with matching calibration; preserve old producers and distinguish native completion from readout recovery. |
| 3. Internal positions | Shared-strip CLI/Control is delivered on selected controls. Complete saved-candidate coverage, full-34-channel fits, independent lateral/depth tests and joint uncertainty propagation. Extend direct full-3D calibration toward all 216 pixels without symmetry substitutions. |
| 4. Fixed-plane closure | Reuse the same-event substitutions and retained photon histories. Apply supported topology/escape alternatives and quantify angular errors and retained/unknown counts on identical candidate IDs. |
| 5. Candidate 3D localization | Generalize empirical candidate preparation, add the exact Cs line and continuous empirical source fitting; incorporate matched passive geometry, observation/selection response and cobalt double-line inference. Then connect joint Cs/Co localization to CLI/Control. |
| 6. Independent statistics | Freeze algorithm/selection, then use retained held-out controls and targeted independent full-chain positions/seeds. Measure distance/direction/strength/depth behavior and failure/unknown rates; larger production still requires the owner's launch decision. |

The implementation uses the existing software and saved inputs; no new frontend,
review rounds or full acquisition restart. Each integrated result advances the
next executable step. A finite optimum or an optimizer covariance alone is not
a calibrated range interval; report open profiles and model sensitivity. Retain
one compact current handoff, source/input hashes and necessary unique evidence.

Owner refinement: prioritize complete usable paths, concrete program/algorithm
defects and usable events excluded by an unsupported interface. Some noisy or
incompatible events remain unresolved; universal event recovery is not required.
Reuse the completed controls and current calculations rather than repeating
validation or expanding difficult-event investigations. The shared-strip
CLI/Control connection is delivered at `fc960f9`; finish its archive coverage
and downstream empirical localization rather than reimplementing that connection.
Hayward's charge-loss/inter-strip work and the ORNL GeGI holdup paper inform
method choices; detector-specific calibration values are not transferable inputs.

## Incorporated roadmap: executable work after the November 21 integration

The external roadmap was written against `982df71`. Reconcile it with the
`fc960f9` handoff and actual source, rather than treating its missing-feature
list as the current state. This is a planning update, not acceptance of new
runtime behavior or an instruction to restart the acquisition. The existing
reconstruction owner retains its workers, lock and scheduled continuation.
Uncommitted empirical-preparation, exact-Cs and shared-strip diagnostic work
belongs to that owner and must be reused when delivered.

Three useful constraints carry forward: performance work preserves physical
inputs and necessary information; detector response stays fully three-dimensional
with all 34 electrodes; current validation uses simulation and primary methods,
without waiting for unavailable measured GeGI data. Keep the six scientific
stages above. Performance improvements are a parallel implementation lane, not
a new prerequisite for every candidate or source-reconstruction delivery.

### Immediate normal-workflow integration

1. **Deliver accepted native numerics to new acquisitions.** The inspected
   `gegi_mixed_acquisition.native_request()` still omits
   `analytic_semiconductor_boundary` and `cached_drift_precision_bits` and sets
   a 1,000 ns drift support. Connect the validated boundary correction and
   promoted drift precision explicitly through request creation, runtime and
   calibration admission. Distinguish field-cache precision from drift arithmetic;
   promoting cached values does not recompute a Float64 field solution. Bind the
   actual model, fields, numerics and readout to a compatible calibration instead
   of removing identity checks. Keep support configurable. If staged continuation
   is used, apply it only to moving step-limited carriers, retain the original
   prefix, and test it against the same configured longer-support calculation.
   Stationary and unresolved cases remain explicit; a longer duration is not
   evidence of collection. Use actual per-group support in unknown-history masks
   and readout frontiers. Reuse the successful and failure witnesses already
   accepted, followed by a small normal-entry integration check if required.
   Do not promise zero failures or a particular unknown-time fraction in a new
   sample, and do not rewrite the original five-second responses or triggers.

2. **Finish shared-strip coverage using the delivered interface.** Preserve
   `--include-shared-strip`, the original 2x2 map and its weights. The saved archive
   has 4,410 shared-topology candidates: 3,833 have matching captured inputs,
   102 lack calibration, 473 have unqualified energy and two are masked. These
   are input-coverage categories, not additional successful reconstructions.
   Process supported saved candidates with original IDs and explicit remaining
   categories; continue interrupted analysis from retained outputs. Carry 1x2,
   2x1 and 2x2 hypotheses through the common candidate/range adapters. Report
   per-topology and combined views without counting an event twice. Compare the
   three line windows on the same original population, including unresolved
   weights. Reuse the accepted selected-trigger CLI and desktop checks.

3. **Finish generic empirical preparation and exact Cs support.** Reuse
   `gegi_candidate_empirical_score.py` and the in-progress preparation work to
   build responses for selected or all supported saved candidates, rather than
   another hard-coded 21-trigger adapter. Inputs must specify candidate identities,
   topology/order alternatives, measured energies, position uncertainty when
   available, the exact geometry and matched response/normalizer. An unavailable
   covariance is unknown, not a zero matrix. Preserve the sealed 21-identity score
   comparison, then exercise genuinely different saved IDs. Add 661.657 keV to
   the empirical sampler with separate fitting/holdout data and required energy
   support; retain 662 keV as a distinct historical line. Do not add unrelated
   photon lines. Exact-Cs sampling is prepared, not yet accepted, at this baseline.

Deliver these changes through the existing CLI and Control, using the usual
software-only release and separate calibration download. Publish new results
through the maintained exhibit generator. No acquisition rerun is needed merely
to publish a planning or presentation change.

### Parallel lossless performance work

The [five-second measurements](gegi_storage_reference.json) record 24,595.746 s
active time, including 16,065.973 s in the native-group scope over 58,684 groups.
That scope includes calculation and data handling. The transport-command scope
records 6,863.203 s over 396 timed calls spanning block processing and retirement;
1,609.468 s of transport-run time is nested inside it. The difference is not a
measurement of process startup alone, and 396 timers do not establish 396 WSL
launches. Separate calculation, serialization, hashing, store operations, launch,
extraction and retirement on retained input slices before selecting changes.

1. Reduce the measured native data-handling cost first: batch requests to the
   resident Julia worker and transfer full-precision binary arrays instead of
   per-group CSV and temporary SQLite round trips where equivalent. Check pinned
   immutable inputs when opening/resuming the worker, preserving producer
   provenance and payload integrity. Keep variable support, signed channel order,
   deposit delays, all neighbor transients and complete failure records. Evaluate
   independent-group CPU threading only with demonstrated thread-local state,
   deterministic results and measured memory headroom. Feed completed groups into
   the chronological readout reducer in the original order and safe frontier;
   parallel completion order must not change the noise stream or accumulation.

2. Measure resident transport reuse independently of block-size changes. Keep
   seeds and source blocks fixed for the first comparison. Choose subsequent
   configurable batch/block sizes from measured time, memory and recovery cost,
   not a universal 100,000-parent default or a fixed thread count. Reuse the
   installed environment. Move retirement only if the same retention prerequisites
   and exact source records are preserved; no original scientific store is cleaned
   up as part of this work.

3. Optimize pending storage or checkpoint frequency only where measured. Pending
   waveform payloads may be separated from the permanent identity ledger, while
   every required failure and candidate remains retained. Account for logical
   records, allocated pages, free pages and indexes separately; noncandidate data
   are not automatically disposable. A durable batch commit must bind consumed
   inputs, failures, candidate/trigger records and the full electronic/noise/random
   state to one frontier, including any external pending queue. Before-commit
   interruption replays uncommitted work; after-commit interruption resumes without
   duplicated or missing groups, even before acknowledgement or retirement.

Use retained same-history controls with overlap, delayed deposits and failures.
For performance-only changes require unchanged payload bytes, or exact decoded
values when serialization changes, and unchanged 34-channel ADC samples, triggers,
IDs, masks and census. Numerical/physical repairs have separately versioned
intentional changes and their own acceptance. Report cold/warm times, peak memory,
peak disk and retained disk on matched inputs. Do not impose an extra one-second
double acquisition, promise 5-15x speedup/60% shrinkage, or turn compiler/backend
replacement into the next task. Reuse accepted improvements for later calibration.

### Internal interaction positions and topology

The coverage target is direct full-3D calibration of all 216 valid pixels, using
the actual field and all 34 weighting potentials. Do not substitute two-dimensional
fields, rotated pixels or translated central responses. Extend usable coverage
incrementally so accepted regions reach the normal workflow before the entire
bank finishes. The proposed 5x5x11 grid is a starting configuration, not a proven
accuracy threshold. Check collected-contact identity and interpolation on held-out
positions; a surface strip width alone does not define the collection basin at
every depth. Treat gap/edge responses separately from smooth interior interpolation,
with unavailable coverage reported rather than silently extrapolated.

Preserve full-precision templates first and use lossless binary compression and
per-pixel loading. Float32 plus a 5 ns time grid changes numerical information;
20 ns ADC sampling and a 20 ns analog time constant do not prove it lossless.
If later explored, keep it a separately labeled approximation with independent
waveform, timing, position and trigger comparisons over ADC phases, energies and
boundaries. Do not adopt the proposed sub-millimeter accuracy, sub-GB memory or
few-minute bank-generation claims as established acceptance thresholds.

Compare the existing refined-depth and XY interpolation methods on matched
independent point and overlap controls before promotion: their isolated-point
improvement does not remove the observed weak-component failures. Add analytic
derivatives only for a supported interpolant and check them against direct
differences. Jointly fit supported energy sharing and coordinates using all
channels; releasing an energy fraction must not silently enforce full collection
or introduce unconstrained loss parameters. Retain alternative fits and explicit
unknown interaction counts.

Use waveform rise/timing/current features and competing topologies to address
merged interactions, but do not gate every alternative solely on a large residual:
10/12 known wrong-topology controls already pass the two-site fit. Reuse those
negative controls and the chronological histories to measure both false acceptance
and loss of clean events; reserve independent controls for final assessment.
Information criteria or residual differences are diagnostics until their error
rates are established. Propagate a joint position/energy/time uncertainty or
retained alternatives, including cross-vertex correlations. Two isolated 3x3
covariance blocks omit those correlations. A regularized inverse Hessian must not
turn a flat, constrained or multimodal fit into a calibrated finite error bar.

### Empirical continuous 3D source localization

1. **Unify the actual scorer and continuous search.** Connect the generic measured
   candidate response and its matched empirical normalization to the existing
   continuous direction/log-radius optimizer. Reuse validated response curves and
   withheld interpolation checks. Keep the declared exterior-source domain tied
   to the configured cryostat geometry rather than allowing internal singular
   optima. Reoptimize direction on each radial shell and compare the far-field
   limit. A smooth normalization interpolant must retain its numerical uncertainty
   and agree with independent direct evaluations; smoothing is not calibration.

2. **Match passive geometry and measurement response.** Include modeled aluminum
   paths consistently in arrival density and normalization using the canonical
   geometry and upstream attenuation coefficients. This corrects unscattered
   transmission; photons scattered in passive material require their own response
   or an explicit unresolved/background class. Convolve supported joint vertex
   uncertainty with the photon model and replace the diagnostic 2 keV width with
   a separately characterized simulated readout response. Include correlations,
   energy sharing and selection bias; do not impose a Fano-like energy dependence
   on a baseline that has no such fluctuation model. Current development photon
   peaks can diagnose a response but are not independent calibration evidence.

3. **Normalize the selection actually used.** For observations y and source s,
   define the selected density from the modeled observation distribution and
   integrate that same distribution over the declared accepted observations.
   Geometry, guard policy, measured strip thresholds, topology availability,
   energy windows and readout quality must match between numerator and normalizer.
   Applying thresholds to true deposited energies or ideal strip IDs alone is
   not the noisy ADC selection. Use independently simulated acceptance where an
   analytic response is inadequate. Retain the existing ideal-topology normalizer
   as a clearly conditional diagnostic until this is available. At fixed joint
   source rates, pileup and unknown electronic history may make acceptance depend
   on the acquisition state; do not silently treat it as a universal single-photon
   sensitivity. Report that scope when interpreting rates or source strengths.

4. **Fit the cobalt lines jointly, then the Cs/Co scene.** Use known emission
   yields b_l in one same-source mixture with density
   `sum_l b_l * f_l(y | s) / sum_l b_l * Z_l(s)` for the stated single-photon
   selected-event model. Equal emission yields do not imply equal selected counts.
   Preserve full-absorption/escape and order alternatives, and include a normalized
   merged/accidental component only where supported. Same-parent two-photon
   coincidences require a joint response or explicit separate class; a line
   mixture alone is not a cascade model. A Cs/Co point-source mixture is the next
   concrete scene closure. Reuse its response and sensitivity for list-mode
   maximum-likelihood expectation-maximization (MLEM) when a distributed image
   is needed. MLEM itself does not establish source number, range identifiability
   or calibrated activity; test those separately rather than adding a second
   general imaging engine now.

5. **Connect and report the result honestly.** Expose supported empirical fitting
   through the existing range CLI and Control alongside the angular diagnostic.
   Report coordinates, radial profiles, line/topology comparisons, unsupported
   counts and original weights. Check the same-event controls before wider saved
   archive processing. Improvement in the 1173-keV corner must follow from the
   response/selection model, not truth-selected cuts. A flat/open profile or a
   boundary optimum is a reportable outcome; neither an interior optimum nor a
   closed distance interval is a mandatory pass condition for the five-second data.

Method references inform these tasks without importing another detector's
parameters: [Yoneda et al., physical interaction and measurement probabilities](https://arxiv.org/abs/2107.01846)
and [Hayward and Wehe, inter-strip interpolation and close-interaction ambiguity](https://websites.umich.edu/~dkw/dkw_personal_website/DSSD_HPGe.html).

### Independent validation and deferred extensions

Freeze the usable algorithm, calibration and selection before statistical expansion.
The remaining saved ideal observations test the mathematical implementation; they
do not replace independent transport/drift/readout observations. Then choose a
compact full-chain matrix addressing a specific uncertainty in distance, direction,
source strength or unequal source depth, after measuring the next computation.
Keep sample sizes configurable and avoid automatically turning every proposed
1-2 s condition into a new campaign. Separate clean, sharing, merged, escape and
unknown populations; report position/angular/range errors, false-order/topology
rates, retained fraction and empirical interval coverage. Test sample-size scaling
rather than requiring exact inverse-square-root behavior in a poorly identified
model. Truth scores completed blind fits only. Document achieved limits instead
of tuning cuts to obtain predetermined accuracy or closed profiles.

The 90.09 s / 20-million-parent case remains a separate owner launch decision,
even after validation. New arbitrary-size acquisitions, GPU drift development,
global Float64 field regeneration, a wholesale package move, unrelated photon
lines and non-GeGI geometry projects are not implied by adopting this roadmap.
Fano fluctuations, diffusion, trapping and crosstalk remain versioned future
simulation options when they answer a concrete question; literature parameters
are hypotheses, not measured GeGI calibration. Avoid double counting charge-cloud
effects already represented by transport deposits. Real-data import remains
conditional on actual data and metadata and does not block the current simulation
objective. Retain the existing environments, originals and unique failures.

## Retained reconstruction evidence

Delivered in the resumed work: original peak/order attribution; all-34 residual
diagnostics; optional portable six-grid lateral correction; candidate-only truth
retention; conditional 3D range profiles and exact far-field comparison. The
full optional lateral run preserves all 3,822 original triggers and weights.
Independent controls reject a residual-only two-site acceptance rule: 10/12
known multi-point mixtures pass, and four extra lateral grids worsen axis error.

Exact original-state transport replays now explain the ten dominant cobalt
contributors. Three escaping 1332-keV photons supply 47.00% of the 1173-window
corner; its two other leading histories contain merged full1173 interactions.
All five leading 1332-window photons are fully absorbed but contain 2-5 Compton
scatters plus absorption in two nominal cells. Their reverse orders supply46.50%
of that corner. No original selection or imaging weights changed. Energy offsets
alone therefore cannot repair both windows.

The portable optional topology path connects 2x2 energy flows and shared-strip
1x2/2x1 ADC fits, preserving unknown interaction count and the full census.
Explicit incident-line diagnostics compare observed-sum absorption and two
resolved Compton scatters followed by escape, with raw kinematic margins and no
truth-tuned tolerance. The1971-group parent repair and537selected duration
continuation are sealed and reconciled:995complete,580failed,385limited,11stopped.
The artificial native-step execution ceiling is removed. Actual1001/5001ns
supports produce a489370980ns conditional unknown union, not restored ADC exposure.
The first tangent/self-hit correction kept20successcontrols exact but allthree
whole-group witnesses still failed. The simultaneous active-surface correction
now restores214613 with32contacts/all34signedsignals and keeps20controls exact;
717723 and3361 continue to1us but remain incomplete. The5us motion diagnostic
exposed cancellation in717723's projection-cost comparison. Stable retained-norm
selection corrects that false stop, preserves20exact controls and leaves both
witnesses moving/limited at5us. The serial580boundary-failure cohort is complete:
51complete,416limited,113stopped, including one exact inherited response.
The reconciled full1971counts are1046complete,801limited,124stopped; no group
remains in the native_failed category. Actual mixed supports give465069020ns
conditional unknown history, retaining1227880ns outside the original mask.
Three original stopped witnesses then separated an exact constrained stationary
corner, a nonzero2.424e-18m sub-coordinate tangent step, and CD_OUTSIDE reaching
SSD's internal-error done branch despite a5.366e-5m unconstrained step. All34
channels satisfy endpoint bookkeeping, but no partial response or old trigger
was promoted. The conditioned-crossing correction now completes119171's23deposits
and46contacts, preserves21previous complete groups exactly, and passes94geometry
and45native assertions. Only this one of124stopped groups matches the cause;
deliver the runtime without another recovery cohort. Preserve the other unknowns.
The first continuous-readout acceptance uses ordinal119/event2459 and43original
successful responses fromb000002, with exactrandom-state/input recovery.
The43responses and exact baseline41triggers/14candidate ADCs now pass. Replacing
only2459adds one guard-only rejected rise, with14candidates unchanged; the
10.563us clipped unknown interval disappears only inside the replayed3.821ms.
The originalb000002safe-frontier extension is complete:43original responses
reused and245regenerated from the frozen producer, all7519rows/15038contacts
verified. The original264trigger records and69candidate ADCs reproduce exactly
before nine available responses enter the same readout/noise history. The
25.119757ms interval then has273rises/98candidates/175rejects;23old excluded
triggers become candidates and six candidates arise at new crossing times.
Six groups remain unknown and192rawblock groups lie beyond the safe frontier.
The conditional mask union changes7,153,400->2,926,760ns with actual1001/5001ns
supports; the longer support adds3380ns in previously unmasked locations.
These are actual continuous-readout changes, not relabeled old triggers or
five-second efficiency. Both first-case and whole-block evidence are consolidated
in the native-response exhibit. No further original block rerun is needed.

The same-ADC hypothesis ledger now preserves all18chronological histories and
three separate peak controls. Five of six clean absorptions have usable fits;
both orders are allowed, with ARM RMS6.84deg true versus41.68deg reverse. The
clean chronological escape retains its true order only under the correct
incident-line escape hypothesis. Five of nine known merged histories still
admit absorption cones, two also escape. An exact linear-template depth split
demonstrates a model ambiguity, not physical resolution. No event weights change.
The explicit escape cones now use the shared finite-vertex radial-profile
consumer. Three six-trigger measured-window cohorts and three separate peak
witnesses retain all24hypothesis/cohort cells:13fully unresolved,10open profiles,
one closed only under an uncalibrated score-drop diagnostic. The1173window's
1332escape optimum141.38mm has just0.28977log-score gain over infinity and no
identified range. Equal precheck order allocation is a diagnostic contrast,
not a new production prior. Fits are hashed before optional truth scoring.
The generic candidate CLI now provides the same fixed-line escape profiles via
`--escape-incident-energy-keV`, with optional original trigger IDs and every
unsupported weight retained. Actual18control and three peak-witness outputs
match the research adapter exactly. Runtime967bdd5 is published with exact public
bytes verified; eight focused range and two targeted package checks pass.
Conditional bulk-Ge photon continuation is now implemented from primary response
derivations: initialized Livermore rates, attenuation, photoelectric path density
and normalized free-electron scatter/escape path-energy density. Three analytic
tests and nine exact saved histories pass, including three actual Ge exits;
coefficient extraction initialized the original configuration with zero events.
`gegi_photon_observed_energy.py` now places both factors in the same observed
second-site energy measure. Nine histories/eight measured energies, seven focused
checks and nested numerical comparisons pass; the rejected adaptive-integral
witness remains recorded. Its explicit2keV test width is not a calibrated response.
The saved measured consumer now computes62of252line/order states across21original
triggers, retaining168incompatible strip-pairing states and22inadmissible fixed
first scatters. Observation tails above physical energy support are evaluated.
Its completed measured response is hashed before photon scoring. Trialsource
geometry now predicts the first outgoing energy and both measured energies
receive explicit response terms; no exact-measured-first gate is inherited.
Six prespecified points compute504supported states with132newly evaluable states.
Stable log densities preserve extreme numerical tails. Two response curves pass
independent-energy interpolation checks (.638%/.437%maximum measured density
errors), reusing failed-coarse-run quadratures. All28unique-pair/order curves now
pass after targeted256/512repair of actual tail-convergence failures. The full
2400point grid computes201600supported states per branch in7.970s; original
geometry failures and underflow references remain explicit. The archived33000native
samples now supply an empirical conditional energy kernel at exact662/1173.228/
1332.492keV, with independent holdout coverage and angular-bin undercoverage
retained.661.657keV stays unsupported. Integrate the same latent outgoing energy
through both measured energies and continuation. That consumer now passes the
same six-point acceptance; the repaired curve overlay restores144uncomputed
escape states, leaving245full/91partial cobalt states.42initialized lower-energy
queries give all336states full coefficient support and absorption coverage;
escape previously retained0.03534-2.11792%uncovered mass in91states. All25needed
lower tails now pass independent checks and all336states have full support.
The normalized empirical angular-energy mixture uses unchanged atoms and retains
the original holdout's undercoverage; no accuracy gain or official weight change.
The full first-arrival/continuation grid and7,200idealized topology normalizers
are complete in88.297s using exact shared spectral factors. The saved21-trigger
source-blind diagnostic retains seven uncomputed records; its nominal1173case
still peaks at the10m boundary. This is a small cohort, not full-five-second
performance. Independent ideal samples at two off-grid sources are now retained:
the first ten each now have sealed blind and subsequent truth scores. All40
ordered curves pass, including one targeted refinement; the faster Gaussian-
measure integral preserves the original references. Both sources select the
nearest sampled direction, but their radial maxima72.999/447.214mm have markedly
different errors. The same20-event continuous external-source fit now completes
all110local optimizations and25radii per cohort; post-score position errors fall
to0.2843/3.1510mm. This confirms coarse angular discretization as a material cause
of the ideal-grid error, not detector resolution or confidence coverage. Reuse
the5,133retained direct endpoint values to extend curves before larger samples;
their240.3s cost dominates the378.5s run. Then evaluate held-out statistical and
physical-response behavior, keeping the exterior-view assumption explicit.
The one global empirical coefficient gap is closed and the joint-atom sampler
passes. Matching empirical normalization now covers both cobalt lines at all
2400positions, with exact pilot reuse and per-point numerical variation. Keep
its numerator and denominator in the same angular-energy measure when applying
it to the retained measured candidates.
Match the empirical normalizer to its joint measure, and keep ideal topology
selection distinct from actual ADC selection and confidence calibration.
Secondary containment, position/Doppler response, passive material and acquisition
selection remain separate. Common units alone do not establish
model probabilities. Angular scores alone cannot choose absorption versus escape or
calibrate source range. Establish coverage, wrong-order rates and angular errors
before changing event weights; unresolved intra-cell scatters need a response
model, not a narrower cone or forced two-point answer. The proven fixed-line
diagnostic is also being delivered through the existing portable candidate-range
CLI, retaining the default absorption workflow and complete original identities.
Then freeze the algorithm for the held-out distance/direction/strength/depth
statistics in stage6. Current five-second results remain development evidence.

The next deterministic chronological sample has 18 exact photon histories:
seven clean two-vertex, nine merged and two with three distinct vertices. Its
same-event substitutions indicate larger angular changes from fitted positions
than from measured energies in the eight fully paired controls (including two
named peak escapes). These remain descriptive, equal-six-per-window controls;
the new observer has now recovered exact photon kinetics on ten same-input
histories with unchanged RNG, canonical transport and native inputs. Those
kinetics confirm the earlier conditional energy-transfer estimates and separate
the transport model's bound-electron angular term from reconstruction errors.
The sidecar is now connected to future candidate-truth retention through the
optional `--retain-photon-kinematics` setting, preserved across resume. Exact
joins on ten retained blocks/34 Ge rows and 38 focused checks pass; the runtime
and same-event comparisons are published at `f52b116`. Ten local injections now
test trigger 12271's shared-charge boundary response. With fixed measured strip
energies, their best sampled model lowers all34 residual RMS from 32.18 to 4.21
ADC codes; three independent local noisy holdouts also improve position error.
This replay-defined neighborhood does not establish blind detector-wide accuracy.
All point endpoints are complete, while the original distributed deposits'
carrier allocation remains unknown. Original selection and imaging weights are
unchanged. The reusable comparison is published. A subsequent grid defined from
measured cells and regular detector coordinates improves the same all34 residual
to10.76codes. Same-clock controls identify template interpolation as the dominant
error:25-28codes versus about2.3codes noise, with negligible energy-only shifts.
Increasing only the lateral-template depth axis from3to11levels improves the
same event to5.01codes and six fresh single-point positions from1.24to0.28mm RMS.
Two of six old overlapping components still worsen, and gap probes remain
outside calibrated XY support. Keep the original unresolved imaging weight.
The six fresh positions now form two layouts tested under three component-energy
allocations,two ADCphases and two noise replicates. All24refined fits converge;
one coarse failure remains. On23matched conditions positionRMS2.055->0.982mm,
but10/69component errors worsen and weak near-ties reach2.36mm. Readout repeats
are not independent photon histories. Three saved conditional profiles identify
lateral interpolation mismatch and weak-component trade-offs: about2mm movement
can add less than0.2ADCcodes RMS after other positions adjust. A fixed same-bank
XY-PCHIP comparison improves six isolated positions from0.285to0.093mmRMS,
but24overlaps show mixed outcomes: weakRMS1.345->1.185mm,only12/24improve,
outer-limit conditions15->16and largestweaknear-tie2.36->2.81mm. Original12271
all34RMS5.01->4.80codes retains unresolved weight1. No runtime promotion.
Joint alternatives now quantify finite-vertex ambiguity on36sameADCcontrols;
the source code variation is retained rather than claiming exact historical-fit
parity. A zero-refit adapter carries all3822saved triggers/7644pairs and original
weights, with coverage separated by local/full34 and center/lateral models.
The12known wrong-topology controls confirm that geometry stability alone cannot
identify two interactions:10/12stillproject, with median spans overlapping the
positive controls. The generic diagnostic now runs without research-fixture
dependencies and with optional all34refits; exact scientific parity and six
package checks pass. Runtime82f6554 is published with exact public-byte checks;
the matching candidate/control exhibit passes local/desktop acceptance.
No threshold or calibrated confidence follows from these deterministic spans.
Then connect supported
responses to interaction hypotheses and source geometry, retaining unknown
topology where the waveforms do not identify it.

**Completed readiness baseline before this resumed work:** the five-second mixed-source acquisition,
its final count/resource accounting and its full saved-candidate imaging are
complete. Verified source, student runtime and site delivery are published, and
scheduled heartbeat `gegi` has been ended and deleted. The owner inspects the delivered
configuration and budget before any 90.09-second/20-million-new-parent launch.
Production remains one physical mixed-source experiment from particle generation
onward; no larger run starts automatically.

**Completed five-second evidence.** The acquisition contains 1,109,875 new parents:
924,676 Cs-137 and 185,199 Co-60, plus 867,305 initial Ba137m daughter decays counted
separately. Of 102,516 deposited groups, 56,713 have complete native response,
1,971 are explicitly unavailable and 43,832 delayed groups lie outside the
five-second window. All 52,371 trigger records remain accounted for; 42,275 are
qualified and 14,909 candidates retain lossless all-34-channel ADC contexts.
Every candidate's saved fast/slow/timing measurements replay exactly. Finite
unavailable-history exclusions cover 0.96563242 s; numerical/domain failures
remain evidence rather than fabricated zero signals.

The canonical `candidate-imaging.json.gz` is a separate 1,901,334-byte derivative
of that archive. It processes all 3,822 eligible two-strip candidates, preserves
the remaining candidate census and closes the image/unassigned-weight accounting.
Original trigger IDs and diagnostic source joins remain distinct from pairing
selection. Calibration admission binds the exact model, field-cache and digital
identities, including the admitted Float32 field state. Full offline processing
took 229.959 s with a 551,071,744-byte process peak; this establishes a working
conditional reconstruction, not experimental detector accuracy or imaging
efficiency.

The retained acquisition is 819,359,442 bytes before imaging. Its sampled run-file
peak was 1,019,254,940 bytes and sampled combined Python/native RSS peaked at
2,609,360,896 bytes. Acquisition active time was 24,595.746 s (6.832 h); nested
Geant4 time is not added again to its enclosing transport-CLI time. One shared
field cache is 857,068,900 bytes and the optional imaging calibration is
303,891,603 bytes, each counted once. Preserve the original prefix data, repair
producer versions, failures and delayed records. The compact accounting is
`.local/steady-acquisition-v1/five-second-acceptance.json`; the completed run and
canonical imaging derivative are under
`.local/gegi-candidate-runs/steady-five-seconds/`.

**Historical readiness delivery (superseded automation state):**

1. Source, student runtime and maintained site are synchronized with GitHub.
   Exact package bytes, desktop Control/map reuse and the corrected guide were
   checked; 1,013 deployed files match the final site build. See PROGRESS.md for
   release and deployment identities.
2. The proposed configuration and measured conditional resource budget below
   are ready for owner inspection. Known numerical and experimental limitations
   remain explicit; no larger production acquisition has been launched.
3. Heartbeat `gegi` was deleted after publication. No automatic development or
   repeated simulation is pending. The owner decides whether and when to launch
   the larger case.

Duration and new-parent-count configuration are now uncapped by the former
five-second/500-parent development ceilings. Defaults remain five seconds and
100 startup parents. Positive-input, identity, finite-window and resource checks
remain; an expected new-parent count is never a bound on chronological transport
IDs, which also cover initial daughters. Two consecutive instances of the same
execution blocker require a cause-specific repair, not an unchanged retry.

### Proposed configuration for owner inspection

Use the same GeGI geometry with Cs-137 at (−40, 0, 40) mm and 185 kBq, and Co-60
at (+40, 0, 40) mm and 37 kBq. Both sources exist before the first decay and share
one absolute clock. Retain the explicit secular initial Ba137m inventory and
quiet electronics start. Transport, drift, overlapping electrode currents,
readout and checkpoints remain continuous across computational blocks.

A fixed duration of about **90.09009 s** gives **20 million expected new parents**
at the combined 222,000 s⁻¹ activity. It does not guarantee exactly 20 million:
the realized parent count is stochastic, and initial daughters are additional.
An exact 20-million-new-parent stopping rule instead has a stochastic duration;
record its final readout-window policy explicitly. Source probabilities are 5/6
Cs-137 and 1/6 Co-60; triggers, usable cones and initial daughters are separate
measured populations. This proposed duration meets the earlier at-least-60-second
production design, but awaits the owner's inspection and launch decision.

The packaged fresh reference gives conditional complete-pipeline scenarios of
about **16–19.3 GB retained**, including the imaging derivative, shared field
cache, shared calibration and preserved evidence once, and about **123–125 active
hours** in the measured runtime. Temporary disk and future peak RAM are **not
bounded** by these figures. The longer-duration daughter mix, failure rate,
checkpoint growth and compute contention may differ; calibration-generation
time is not included. The original encoding is unchanged. These are planning
scenarios, not confidence limits, a storage upper bound or a readiness guarantee.

### Earlier bounded integration and format evidence

**Historical startup evidence:** the mixed-source generator, existing native worker,
continuous readout and conservative candidate store are connected in Control.
All available signals enter readout; clean single-pixel and guard-only records
keep counts/reasons without waveforms. Multi-strip and ambiguous candidates keep
one lossless all-electrode context and exact fast/slow/timing measurements. The
100-parent fresh startup has 83 Cs / 17 Co parents, 98 zero-deposit parents, one
in-window single-pixel trigger and no candidates. A delayed daughter deposit at
about 206 s is outside this sub-millisecond startup window. No pre-existing
daughters are assumed. This is a small integration acceptance, not equilibrium
source operation or validated imaging efficiency.

The historical 50 ms saved-signal storage diagnostic has 11,293 scheduled parents, 418
qualified triggers and 144 retained candidates, with exact readout replay for
every candidate. Its compact archive is 1,007,616 bytes and its shared group
ledger is 31,951 bytes. Its earlier 1.81–2.34 GB format-only candidate-core
projection excluded fresh source/failure/late records. It is superseded for
current planning by the measured five-second reference and whole-retained budget
above; the replay remains applicable continuity evidence. The zero-candidate
startup is not a storage-yield reference.

**Delivered streaming implementation:** bounded transport/current blocks now
preserve pending daughters and electronics state in resumable checkpoints.
The recorded 100-parent split-50/50 fresh run, 50 ms two-restore check and 102 ms
steady-source check provide continuity evidence; reuse the exact applicable
receipts in PROGRESS.md. Final five-second accounting and full candidate imaging
now add the measured evidence summarized above. Do not infer a whole-run disk
budget from final candidate archive size alone.

The earlier [25-window readout study](../docs/results/gegi-shared-readout/index.html) used archived per-isotope histories in one shared electronics simulation per 250 ms window. It provides a readout comparison, not a completed full-generation run under this plan.

### Maintained mixed-source contract (implemented; production awaits owner)

The implementation reuses the existing geometry, fields, carrier transport and
readout functions, connecting fresh mixed-source generation to continuous detector
state. Record these inputs and outputs for each new or resumed acquisition:

| Boundary | Required record and acceptance |
|---|---|
| Source generation | Both isotope definitions, positions and activities are present before the first decay. Record the acquisition start state, source age or initial daughter populations, pre-acquisition history policy, random seeds and generator version. Do not silently assume an empty detector or secular equilibrium. |
| Identity and time | One immutable acquisition ID and unique parent-decay ID identify the isotope and position. Daughter, emission, transport event and deposit IDs retain their parent relationships and absolute times, including delayed daughters across buffers. A trigger may contain multiple parents; one parent may contribute to multiple triggers. |
| Continuous processing | Carry pending daughters and current tails, preamplifier/shaper/filter state, noise generator state, ADC sample index, trigger state and unfinished readout windows across buffers. A checkpoint also binds configuration/input hashes and the last committed identities so restart neither repeats nor drops records. |
| Bounded acceptance after resumption | Process the same finite fresh-source input continuously, in several buffer sizes and through stop/resume. Compare identities, time ordering, deposited energy, signed charge, ADC codes and trigger/reconstruction records; document any necessary numerical tolerance. Place delayed emissions and overlapping pulses at buffer boundaries. Retain zero/nonzero/failure/unknown counts and close every stage's census before scaling. |
| Production | After published readiness and owner inspection, launch only the approved uninterrupted acquisition. The proposed 90.09 s case satisfies the at-least-60-second design. Report actual parent decays, deposits, triggers, accepted energies, usable imaging candidates, exclusions and unknowns separately. A completed pipeline alone does not establish instrument accuracy. |

At the specified constant activities, the expected 60 s parent census is
222,000 s⁻¹ × 60 s = **13,320,000 parent decays**, not triggers or imaging events.
Assuming 34 channels, 50 million samples/s, 60 s and two bytes/sample, a complete
uncompressed ADC stream would occupy **204 GB (about 190 GiB)**. This is a storage
estimate under explicit assumptions, not a measured output size. Candidate-only
retention is implemented and its five-second throughput/resources are measured.
Use those conditional rates with the recorded buffers, trigger contexts, ledgers
and checkpoints; larger-duration peak resources remain unvalidated. Existing
scientific originals remain unchanged.

Fix reconstruction selections, interaction-order rules and imaging priors before
independent evaluation. Split by original history or fresh parent-decay identity;
repeated replays of one history are not independent evidence. Use source-position
truth only to score final estimates. Report error with returned/total coverage,
failure rate, energy/position range and uncertainty. Existing AK02/SAP22 measured
spectra support a bounded spectrum comparison; no historical measured waveforms
exist. GeGI comparison needs matched channel mapping, calibration, thresholds,
pixel selection, acquisition time and normalization.

### Earlier saved studies

**Completed imaging baseline.** The four-block ±120/±240 mm comparison and the held-out angular-response check are complete. Students can replay the same measured cones under either plane prior and compare the maps in Control. Uniform solid angle stabilized the pooled peaks on widening, while the 662 keV peak moved farther from the simulated Cs-137 position when the prior changed. Both selectable assumptions and the original event denominators remain in the [published comparison](../docs/results/index.html#gegi-plane-priors).

**Shared-clock evidence.** All 324 measured two-strip rises were recovered from their 34-electrode ADC samples. Their finite ADC, fast and slow supports contained no additional reference Ge onset. The full 3,905-trigger population did include two merged timing assignments with more than one depositing group in one rise. One measured 858.219 keV on one X and two Y strips, and the other had guard collection and no accepted energy. In 24 matched pulse controls, the local ADC window recovered seven second rises. At 600 ns the full clock registered both triggers in all six trials, after the first window had closed.

**Matched component controls.** Replaying the groups from triggers 683 and 598 together reproduced all 1,972 saved ADC codes. Separate replays showed two clean energies on a shared X strip in 683. In 598, only the Co-60 group triggered the guards. Its signals on Y13 and Y14 contributed to the Y strip sum although no carriers ended on those strips. The [handoff](../PROGRESS.md) records the original and isolated outcomes and the retained noise and history.

**Weak strips and pairing.** The [fixed late-step study](gegi_weak_strip_study.py) flagged 2/59 energy-incompatible and 5/265 compatible triggers. All ten flagged strip signals had a [simulated carrier landing](gegi_weak_strip_endpoints.py), including one below the nominal sensitivity floor. All 57 unflagged failures distributed their energy over three or four intersections of the four measured strips. The study is a GitHub Pages exhibit. The student package and the measured pairing rule are unchanged.

**Image contribution from three intersections.** Two triggers in each Co-60 energy window supplied over 41% of the original peak cell on the ±120 mm uniform-area image. Setting them aside moved the peaks 236.0 and 59.5 mm at 1,173 and 1,332 keV. Both cobalt pairs reused a single archived history within their respective window. The solid-angle maxima stayed in their original cells. The [existing imaging exhibit](../docs/results/index.html#gegi-three-intersections) gives the full and retained peak coordinates, the source-position comparison and the leave-two-out denominators.

**Origin of the two cobalt contributions.** In both archived histories one Co-60 photon deposited its full energy in Ge. Four Compton scatters preceded absorption in the 1,173 keV history, and two preceded absorption in the 1,332 keV history. The two-cell readout allowed only the reverse of the dominant first-to-final cell order. The [existing imaging result](../docs/results/index.html#gegi-three-intersections) connects the original photon steps to the measured strip energies and cone directions.

The matched pulse-overlap test supports the existing channel-local quality flags. The 4 keV-per-sample coincidence option recovered 19 of the 45 missed isolated deposits; the original 5 keV setting remains selectable. The 80-point continuous single-pixel calibration transfer, nine additional lateral strip-pair checks, and per-pixel energy-window/spectrum workflow are recorded in the [handoff](../PROGRESS.md). These local development steps proceed independently of stable-release approval and measured-data comparison.

1. Control and the command line now run a configurable simultaneous acquisition from two supplied GeGI source libraries. The [student guide](site_guide.html#gegi-dual-source) covers placement, activity, exposure and the saved count/spectrum receipt. A 0.25 s reference exposure and a 0.05 s changed-activity acquisition are recorded in the handoff.
2. For routine owner-authorized GeSignal updates, synchronize the verified revision using the existing administrator permission. Publish a stable student release when the runtime changes. Update research exhibits on GitHub Pages, remove superseded displays and verify the deployed files.
3. The two edge scans motivated by event 2950 are complete. The wider fast-ratio and timing calibration returned a coordinate at 16/24 independent positions. On those same positions the one-axis RMS error was 1.117 mm, compared with 0.389 mm for the timing-only fit. Keep the current student position calibration and existing photon-order alternatives. The [handoff](../PROGRESS.md) gives the full denominator, measured strip-center fallback and gap-midpoint comparison.
4. Control and the standalone map exporter now read the measured 16 × 16 strip-intersection map from saved dual-source reports. The 0.25 s reference maps 484 of 864 triggers to 176 pixels. The changed-activity case maps 113 of 259 to 80 pixels. Both censuses close when multi-strip energies and triggers without energy are included.
5. Use the next matched experimental acquisition to check the fast/slow feature scales and ImagerPro pixel selection. Compare channel and pixel spectra with matching population, calibration and normalization. The 32-channel simulated spectrum export is ready.

Reuse complete saved signals for electronics changes. New transport or drift needs an identified missing physical input. Keep the student download software-only and publish saved studies through the website generator. [Previous development record](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/9941f0d663e835a225e43923e6271b3b8df17d17/tools/NEXT_DEVELOPMENT_PLAN.md)

The controlled study uses continuous digital filtering and independently tests trigger separation and pulse-height recovery. These design choices have published precedents in trapezoidal pulse shaping and commercial digital spectroscopy. The GeGI trigger parameters and neighbor-position observable are simulation assumptions. [Jordanov and Knoll (1994)](https://doi.org/10.1016/0168-9002(94)91011-1) · [XIA Pixie-16 User Manual, digital signal processing](https://s3.us-west-1.amazonaws.com/download.xia.com/products/pixie16/documents/manuals/XIA-Pixie16-Users-Manual-3.06-2019-09-13.pdf)
