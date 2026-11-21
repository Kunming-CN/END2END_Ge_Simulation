# GeSignal handoff

## Active work and continuity

The owner resumed the full signal -> interaction -> source-position queue after
8d7c76e. Current-thread heartbeat `gegi` is ACTIVE every30minutes. Follow
[the six-stage plan](tools/NEXT_DEVELOPMENT_PLAN.md); no resets, extra reviewers,
new frontend or automatic90.09s/20M production. The completed five-second run is
unchanged. This interface cannot verify/switch the leader to GPT-6 Astra Ultra;
no switch claimed. Workers are explicit6.2SolUltra(candidate/position) and
6.1SolUltra(native), with current ownership below.

Owned lock `.local/autonomy/gegi-reconstruction.lock`, thread
`01a1fd1a-3e72-7eb2-b7bf-c8c2d59236fd`. Inspect actual markers/checkpoints before
launching or writing pinned sources. Do not start another native worker.
Default sandbox process lookup can be empty even while its elevated owned
session advances; a narrow elevated read-only lookup verified the exact PIDs.

* **Native worker:** `/root/native_response`, session74071, Python17496/Julia29040,
  phase `.local/gegi-reconstruction-v1/native-recovery-segment-crossing/`.
  Request SHA c709ec329bae0ab05789970b1a234d7d0bb7c17ae45a5049757cf86a55cbfaac.
  Latest checked 1619/1971: 701 complete, 441 step_limit, 473 failed, 4 stopped.
  This is a running prefix, not the final repair rate.
  Actual checkpoint/active-worker/native SQLite are authoritative. One earlier
  109-group phase retains39complete/29limit/41failed; only the exact39complete
  records were inherited. Diagnostic.jl drift-only work remains untested WIP,
  excluded from releases. Finish the existing phase, reconcile all1971 and mask
  union, then remove the artificial20000-step ceiling and test same moving-tail
  inputs with actual configured support reflected in unknown-history bounds.
* **Candidate worker:** `/root/candidate_attribution`. All 18 prespecified non-peak
  histories are complete: seven clean two-vertex, nine merged, two with three
  distinct vertices; 17 full-energy photons and one escape. All 18 exact
  primary/RNG/canonical-stream/native-input comparisons pass. Selection remains
  six chronological ranks per window, not a population-weighted or new-seed test.
  Receipt `chronological-window-origins/origins.json` SHA
  410e4705e8cc3ee6c809998339b06c86dcd0b1c543c29951a3d2fd0860c4f0fe.
  The optional photon-step observer passed exact primary/RNG/canonical-stream/
  native-input parity on ten original blocks. Its 130 photon steps include
  15 Ge Compton steps and 34 unique original Ge-row joins. The original
  executable and archive are unchanged. `photon-step-observer-v1/kinetic-audit.json`
  SHA fc35c110a09fc39a13d063ceac7b81b10de9d955c14f93e6cbf2fcaab6e9702f.
  Future candidate-truth integration is implemented and tested. New acquisitions
  opt in with `--retain-photon-kinematics`; resume restores the saved choice.
  Exact steps attach to the original Ge rows in `candidate-truth.jsonl.gz`.
  All 34 retained Ge rows from ten blocks pass the real input join/staging
  acceptance; 24 transport/observer and 14 acquisition checks pass. No new
  acquisition or native calculation was needed for this integration.
* **Position worker:** `/root/position_model`. Same-event substitutions on all
  18 chronological IDs plus three named peak controls are complete. Among eight
  fully paired cases, position-only |ARM change| is 0.44-16.59 degrees versus
  0.005-0.049 degrees for energy alone. Five chronological absorption controls
  give ARM RMS 2.417 degrees for true vertices plus retained transfer estimate,
  6.841 for positions only, 2.396 for energy only, 6.844 for both. This earlier
  conditional estimate is preserved in `same-event-substitutions.json`, SHA
  d4df4a23ac615b63d691b9faabe9ef0a50b181049614ec18849d21dba293860d.
  Exact photon kinetics now confirm its transfer estimates within 2.27e-13 keV
  on the observed controls. The new receipt retains all 21 original IDs and
  weights: ten observed histories, eight complete signal substitutions, one
  clean truth-only case and one merged case without a false two-site match;
  eleven histories have no observer. Source alignment, bound-electron model,
  position, measured-energy and nominal-line angular terms are separate and
  sum within 1e-10 degrees. `same-event-exact-kinetics.json` SHA
  9bca9f3d43f5f7fba86965873fe6a431934b2309953cc8343eb3a51dab4e0cd8.
  Photon vertices, deposit centroids and signal positions remain distinct.
  Trigger 12271 is explained at the nominal deposit-cell level: the second
  photon deposits 365.027/105.176 keV across Y27/Y28. Four strip totals match
  measured energies within 0.102 keV; the three-cell fit recovers the allocation
  but retains 32.18 ADC-code overall RMS and 138.26 on Y28. A four-cell fit is
  nearly tied. The original unresolved weight stays one; carrier endpoints are
  unknown. `trigger-12271/charge-allocation-diagnostic.json` SHA
  3cf6a6738ea846a037b3b94262602792473b8307e1b49b3b0ab6c91e969c362d.
  Nine existing banks contain no off-center response in these three cells.
  The exact-kinetics receipt specifies ten unrun 500-keV all-channel points,
  including independent holdouts. Run them serially after the active native
  worker and its priority cause diagnostics; reuse the existing field cache.

## Delivered reconstruction and scientific findings

Commit `f65c25b7003c41e0082e5e7cd884815d726502bf` is published on GitHub main.
Control traces a source-plane peak -> trigger/pair/order -> original34-channel
ADC. Full34 residuals, optional six-grid lateral positions, future candidate
truth retention and conditional finite-vertex3D range profiles are portable.
Shared-strip and2x2 topology diagnostics plus complete incident-line kinematics
are in the software-only release. Current official maps/selection are unchanged.

The main causal result is established by exact original-state transport replays
of the ten dominant cobalt contributors. Three escaping1332-keV photons supply
47.0007% of the1173-window corner; two merged full1173 histories add14.3559%.
All five leading1332-window photons are full-energy with2–5 Compton scatters
plus absorption; reverse nominal-cell orders supply46.5032% of that corner.
All primary/RNG/canonical-stream/target-native-input hashes match; LH5 container
byte hashes differ. There was no native/readout rerun, and earlier electronics
tails remain unisolated. `cobalt-top-ten-origin.json` binds the exact producers.

Trigger12841 merges two vertices4.54micrometres apart and is forced into an
incorrect reverse9.18deg cone. Its corner ARM53.896deg is5.65effective widths;
raw angular density2.779e-7/rad becomes0.02681trigger units after finite-grid
normalization,24.79% of the peak. Source density is2.365e-21/rad. All ten peak
shares reproduce within8.33e-17. `peak-tail-diagnostic.json` SHA
87e32633dfb8f1756df9bce46f2b4aab365e224e14d2d4ebfd3c3455ed2551c2
retains both120/240mm grids. These conditional densities are not efficiencies.

All3822 triggers/7644 pair alternatives are retained in the full incident-line
ledger, including4607 incompatible alternatives. At1332.492keV, nominal two-
scatter escape orders carry only13.06% of the original1173corner. Compatibility
also admits Co escape in Cs candidates, so it cannot identify an isotope.
Energy-window narrowing cannot fix both corners:1173half-peak-weight needs
|offset|4.577keV;1332half-weight is within0.091keV. No cut was introduced.

Independent ADC controls: full34 lateral vs full34 center on36 matched conditions
improves axis10.26->5.00deg andXY1.80->1.04mm. Six grids support151/2983pairings,
not the whole detector. Four other grids worsen axis7.17->9.32deg and were not
promoted.10/12 known multi-point conditions still produce two-point cones with
small residuals; no residual gate is justified. The full optional lateral replay
preserves all3822 IDs/weights/peak cells; conditional3D fits move0.16–0.47mm.
Shared-strip census4410, of which3833have usable measurement/templates;32actual
fits converge,16injected conditions overfourlayouts give axis5.04deg/depth0.184mm
RMS. This establishes usable fitting, not photon multiplicity identification.

The3D adapter fits free direction and center distance, source/activity unknown.
Fixed25% extra-background Cs/1173/1332 ranges are55.19/56.21/64.40mm; clock-half
shifts1.64/43.61/28.85mm. Profiling background gives55.41/56.32/64.92mm. Cobalt
remains strongly model-sensitive. Profiles are conditional, not calibrated
confidence intervals. The independent statistics stage follows fixed response
and selection; current five-second data remain development evidence.

## Current integrated changes and publication

New conditional escape geometry CLI is implemented/tested, with no imaging
weights or source input.13conditional cones/71inadmissible orders were recorded
on21selected triggers overthree supplied lines. Verified42261/19477 true-order
ARM becomes+15.26/-6.46deg;12841 remains without a resolved escape cone.
`conditional-escape-geometry-controls.json` SHA
43b60e4766f6c7812dc5b3b449b43fabd68a08fd489c2a0f1ecb910cfd6671a6.
Three focused geometry tests and six unpacked-package checks passed.

The remaining continuous parent-count100M ceiling is removed; positive integer
format stays.18clock/checkpoint tests pass, including a100000001 configured count
that produces onlyfive clock rows across resume. No new acquisition launched.
Initial sandbox hard-link test failures were permission errors; the unchanged
suite passed with normal permissions. Active transport uses frozen original
source; native request has no pin to this changed module.

Source, software-only package and website milestone `f65c25b` are published.
Website build `e490cc275ba69674c23289291da75746b0b2990b9a431c7ec1dd403c65c53815`
contains 1,914 files / 512,600,559 bytes. Required 42 publication tests, local
site check and two display tests pass. Desktop Chrome checked the raw-density
explanation, conditional escape results and new CLI guide. Required live check
verified 1,018 files, including all five exhibit files. Preview sessions closed.
Release `student-runtime-f65c25b7003c`: 1,393,756 bytes / 252 members, SHA
4dc2fab9280e13b7f7a282e05c44776065da8ce0e7f8d98ab803d0e38100738a;
public bytes match. `publication-assets.json` is the combined receipt. Center
and `gegi-lateral-calibration-v1` downloads remain separate and unchanged.

The new photon observer remains outside this release. Ten same-input sidecars
have exact primary/RNG/canonical-stream/native parity; session 82114 exited0.
First receipt `photon-step-observer-v1/b000050/observer-verification.json` SHA
900255ab37e41a8db53e635b336306612ab02a558eb2ce291220ff74474246fe.
The first receipt writer had a path-type error after transport completed; it
was corrected from retained outputs without rerunning. Source is in
`transport/gegi_photon_step_observer.cc` and `transport/gegi_photon_steps.py`;
the transport allowlist names these and their focused test explicitly.
Three reader/configuration tests pass. Nine measured replay calls total
79.486012193 s with peak RSS 182,534,144 bytes; the first call lacks a process
resource receipt after its preserved writer error. No repeat transport was used.
Observed exact energy/angle differences are separate from measurement errors;
the frozen macro chooses Livermore, whose Geant4 11.3.2 Compton model includes
bound-electron momentum and shell binding. No per-step shell label is recorded.
Exact-energy substitutions and future-truth integration are complete. The latter
acceptance SHA is 773088ef540dc50398d69032665d9b388c39a7d243ee86b9c86972d5e55536aa
at `photon-step-observer-v1/candidate-photon-retention-acceptance.json`.
The original reader bytes remain in the observer build evidence, preserving
the first receipts after the reader extension. The package manifest now includes
both observer sources; six package checks pass. The existing exhibit adds all
21 exact-control records and the eight additive angular comparisons. Two display
checks and 42 publication tests pass. Site build
`90f02331125a1685927e7915e6501bc41a90221e9b2d6b05019ff434c560a316`
has 1,914 files / 512,749,015 bytes and passes the local site check. Desktop
Chrome verified homepage -> result -> expanded exact angular table and the
photon-retention/resume guide. The first sandbox preview could not be reached;
the owned localhost preview worked outside the sandbox, and both preview
processes and the tab are closed. Source/package publication and live checks
are pending. Native diagnostic WIP remains separate until tested.

## Baseline and retained evidence

Original `.local/gegi-candidate-runs/steady-five-seconds/`:924676newCs parents,
185199newCo parents,867305initial daughters;102516deposit groups=56713complete
+1971unavailable+43832after5s.52371rises,42275qualified,32502energies,
14909retained;3822two-strip and11087outside that model.2891.5projected+
930.5unresolved are trigger weights, not efficiency or physical event counts.
Original unknown history0.965632420s(19.31%) is not hardwaredeadtime. Native
repair alone does not restore old continuous triggers or justify removing masks.

All new evidence lives under `.local/gegi-reconstruction-v1/`. The accepted
five-second run took6.83active hours, retained819359442bytes before imaging,
peakfiles1.019GB/combinedRSS2.609GB. Conditional90.09s/20M estimates15.77–19.26GB
and123–125activehours exclude new diagnostic truth overhead and are not launch
authorization. No waveform library replay qualifies as joint-source production.

Earlier exact results, producer hashes and publication history remain in the
[immutable integrated handoff](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/ee7c3ca73a1a39a68421f43493e196831dc2b555/PROGRESS.md).
Use [the maintained guide](tools/site_guide.html) and [source ownership](tools/MAINTENANCE.md).
