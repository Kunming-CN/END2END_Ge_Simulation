# GeSignal handoff

## Active reconstruction development — November 21

The owner resumed signal -> interaction -> source-position development after
`8d7c76e`. The current-thread heartbeat `gegi` is ACTIVE every 30 minutes. Continue
this queue; do not restart the completed five-second acquisition or launch the
90.09 s / 20-million-parent production case. No resets or extra review agents.
The six-stage delivery order is in tools/NEXT_DEVELOPMENT_PLAN.md.

Owned lock: `.local/autonomy/gegi-reconstruction.lock`, thread
`01a1fd1a-3e72-7eb2-b7bf-c8c2d59236fd`. Inspect actual worker/process/checkpoint
state before writes or launches. Worker assignments are explicit GPT-6.2 Sol
Ultra (candidate/position) and GPT-6.1 Sol Ultra (native). This interface cannot
verify or switch the leader to the requested GPT-6 Astra Ultra; no switch claimed.

**Implemented and evaluated; integrated publication is in progress.**

* Peak attribution reproduces all three original five-second maps to 2.90e-14
  trigger units. Trigger 12841 / pairing 0 / reverse order supplies 24.79% of the
  1173 keV (+118,+118) mm peak; leave-trigger-out moves it 236 mm. Enlarging the
  same uniform-area projection moves the peak to (+238,+238). The 1332 keV corner
  is also unstable. Both cobalt windows move near the programmed source under
  solid-angle weighting; this does not validate that prior or causal photon
  interpretation. Original selection is unchanged. Exact per-trigger/order,
  time-block and footprint evidence: `five-second-edge-attribution.json.gz`.
* Control's peak-contributor path opens the original 34-electrode ADC context.
  Desktop Chrome verified 1173 keV -> trigger 12841 -> electrode 8 (81 samples),
  without starting a simulation or download. Optional all-34 residual diagnostics
  leave the original fitted parameters, selection and maps unchanged.
* All 2,983 saved fitted pairings were rescored on all 34 contacts. Center-model
  all-channel refitting alone did not improve held-out position errors. For the
  same 36 general controls, full34 lateral vs full34 center reduced axis RMSE
  10.26 -> 5.00 deg and XY RMSE 1.80 -> 1.04 mm. One-site lateral improved all 12
  conditions at one independent geometry (axis 5.204 -> 2.997 deg). The six
  position-tested grids support 8 two-grid and 143 one-grid fresh pairings:
  151/2,983 = 5.06%, not detector-wide coverage or validation.
* Portable opt-in lateral corrections use a separate 18,083,717-byte overlay,
  SHA bfc881bd3210720ef0cc69fe8c767f7080539ce792b11f72fff2c7befce2d824.
  It binds the original center bundle and retains explicit per-site support and
  fallback reasons. Actual trigger 14 reproduces its evaluated one-site lateral
  positions exactly; 12841 explicitly remains center. Saved geometry survives
  the contributor/range adapter exactly. Existing center defaults are unchanged.
* Independent topology controls are decisive: 10/12 known three-/four-point
  conditions still produce valid two-site cones. Their full34 residuals overlap
  or undercut true two-point controls; timing and parameter bounds do not reject
  them. No residual gate adopted. The 56 positive conditions share five physical
  geometry groups, not 56 independent geometries. Signed position/energy errors,
  group covariances and every outcome are in `position-uncertainty-controls.json`
  (SHA 6accb91c8e3076b0b535e5d3a1fea662c951450aab9645b97a1c9ad79fcccd24).
* Historical same-event controls retain 41 matched occurrences / 27 groups, but
  only two full-energy photons and no full 1173 keV example. Photon vertices,
  energy-weighted deposit centroids and signal estimates stay distinct. Fresh
  complete transport survives only in b000000/b000001, not the other 198 blocks.
* Three-dimensional scoring now reads the fresh saved candidate geometry,
  preserves order/unknown weight, and fits full-sphere direction and center
  distance without source truth/activity. The refined 49-radius / 192-direction
  / 6-start fit agrees with an expanded search to <0.001 mm. Primary Cs, 1173,
  1332 positions are (-39.4918,-0.2103,38.5483), (38.3649,-0.2415,41.0839),
  (40.1099,1.5901,50.3560) mm. Clock-half differences are 1.64,43.61,28.85 mm;
  background sensitivity remains large. `candidate-range-refined.json` records
  123.21 s. The earlier coarse numerical miss remains preserved.
* Profiling the extra uniform-angle fraction at every position, and comparing
  the exact far-field limit, gives center distances 55.41,56.32,64.92 mm and
  fractions .317,.666,.434 for those windows. Finite-minus-far scores are
  199.64,9.37,19.62, not significance levels. `candidate-range-profiled.json`
  (218.76 s, SHA 59822b5c5a83ef28fbc7e657ba22a64a94c07923de799c7d61ecf2117f7cdbb8)
  retains all fitted profiles; its exact four-file producer ZIP is preserved.
  Closed scores are uncalibrated; an open edge or supported far field leaves
  distance unidentified. Six focused mathematical tests pass.
* Future acquisitions separately retain candidate-linked photon ancestry, scored
  Ge chords (including zero-edep gamma steps), positive deposits and native
  endpoints before scratch retirement. `candidate-truth.jsonl.gz` does not feed
  reconstruction. Context joins are not causal photon assignments. Read-only
  checks of two original blocks reconcile all 1,000 transport records, 993
  positive Ge deposits, 117 gamma chords and 603 births, with original hashes
  unchanged. Thirteen streaming/stop-resume tests and 17 transport tests passed;
  no transport or field solve was repeated. Completed truth export is checked
  before returning a resumed completed run.

## Native response recovery and immediate continuation

All 1,971 missing groups are classified: 644 step-limit, 918 stopped, 409
exceptions (238 contact-start, 170 outside endpoint, one signed-charge error).
All 308 contact-classified deposit rows in the 238 groups are outside contacts
under Float64 arithmetic on the same geometry. A contact-at-limit flag defect
affects one endpoint but recovers zero complete groups. Undefined SSD terminal
rows now produce precise deterministic diagnostics before interpolation.

The first Float64/analytic-boundary replay was cooperatively stopped after 109
groups when a concrete projected-boundary defect was established. It durably
retains 39 complete, 29 limit and 41 failed groups in `native-recovery64/`.
The first20 timing/resources remain separate: 9 complete, 79.44 s native work
including compilation, sampled native RSS 3.68 GB. This chronological prefix is
not a population recovery-rate estimate. Original scientific outputs are intact.

The coarse 0.001 projected-step backoff is corrected using SSD's existing
segment crossing routine. Two retained failures reach genuine
passivated corners without collecting contacts; their remaining signal stays
unknown. Twenty successful controls remain complete. The standalone error path is fixed.
The active pinned phase `native-recovery-segment-crossing/` inherits only the 39
exact input-matched complete records and processes all other originals; request
SHA c709ec329bae0ab05789970b1a234d7d0bb7c17ae45a5049757cf86a55cbfaac.
Inspect `native-recovery*/active-worker.json`, logs, identity and checkpoints;
do not launch a competing Julia worker or modify active pinned producer files.
Native recovery does not reconstruct the previously omitted continuous readout.

The current phase reached 202/1,971 durable records: 84 complete (including 39
inherited), 54 at the configured drift limit and 64 specifically stopped at an
uncontacted face intersection with no positive projected motion. This prefix is
not the final recovery fraction. Python 17496 / Julia 29040 remain active.

The full optional lateral replay preserves all 3,822 trigger identities, orders
and 2,891.5/930.5 projected/unresolved weights. It uses 143 one-site and eight
two-site corrections; all three original peak cells are unchanged. Four 3D window
fits move only 0.16-0.47 mm, while background sensitivity remains much larger.
Measured replay/range time is 362.24/240.80 s, peak resident memory 651/296 MB.
`candidate-lateral-acceptance.json` retains the exact inputs, outputs, producer
ZIP, versions and all paired profile comparisons.

Shared-strip census finds 4,410 retained 1x2/2x1 candidates, 3,833 with qualified
energy, intact ADC context and both templates. The others are 473 unqualified,
102 missing templates and two masked histories. All 32 systematically sampled
ADC fits converge; 16 independent injected conditions over four layouts give
5.04 deg axis RMS and 0.184 mm depth RMS. This expands a usable experimental
input interface, not identified photon topology. The separate shared-strip
study and ADC three-/four-corner study preserve alternatives without changing
the released two-strip map. The latter shows residuals cannot choose topology.

Immediate work: finish native recovery and same-input moving-tail extensions;
connect the measured sparse/continuous energy-flow hypotheses through an optional
portable CLI; evaluate ambiguity before replacing default event selection.
Four additional archived lateral grids failed to improve aggregate axis error
(7.17 -> 9.32 deg) and were not promoted into the six-grid calibration.

Publication acceptance is complete locally: build
`b173155aa8f5375c9b02229264d9decc26ebaa1c466d328f977d44eb151954b4`,
1,912 files / 505,937,620 bytes; 42 publication tests, 13 route tests, six package
checks and the UI contracts passed. Desktop Chrome verified Control's saved
range profiles (including an open 1332-keV no-background profile), lateral
controls, and homepage -> new exhibit -> methods. Preview servers are closed.
Commit/push, exact software-only student release, separate lateral calibration
release and live byte verification follow. Keep the heartbeat active through
the remaining development queue; no large production run has started.

## Preserved baseline and history

The original `.local/gegi-candidate-runs/steady-five-seconds/` contains 924,676
new Cs parents + 185,199 new Co parents + 867,305 initial daughters. Of 102,516
deposit groups, 56,713 completed, 1,971 were unavailable and 43,832 lie after 5 s.
There are 52,371 rises, 42,275 qualified triggers, 32,502 measured energies and
14,909 retained candidates. The two-strip model covers 3,822; 11,087 remain
outside it. Projected 2,891.5 + unresolved 930.5 are nominal trigger weights,
not physical event counts or efficiency. The original unknown history covers
0.965632420 s (19.31%), not hardware dead time.

Original acquisition active time 24,595.746 s (6.83 h), retained 819,359,442 bytes,
peak run files 1,019,254,940 bytes, sampled combined RSS 2,609,360,896 bytes.
The shared field is 857,068,900 bytes, center calibration 303,891,603 bytes and
original imaging 1,901,334 bytes. Measured conditional 90.09 s / 20M projections
are 15.77–19.26 GB including optional analysis and 122.86–124.54 active hours;
they are planning scenarios, not launch authorization or guaranteed maxima.

All new local evidence is under `.local/gegi-reconstruction-v1/`. Exact earlier
receipts, package history and numerical qualification remain in the
[immutable pre-development handoff](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/8d7c76ea63cc0d4876722caadb8db8856b6d633d/PROGRESS.md).
Use the [maintained guide](tools/site_guide.html), [development plan](tools/NEXT_DEVELOPMENT_PLAN.md)
and [source ownership](tools/MAINTENANCE.md); preserve originals and unique failures.
