# Current development plan

## Next saved-data milestone — new-chat continuation

Prepared at the owner's request on 2026-10-20; not started. An owner-sent
continuation prompt starts this work. Reuse the completed diagnosis and correction
artifacts rather than repeating them. Keep automatic monitoring PAUSED.

1. Refine existing event classifications into spectroscopy, supported imaging,
   ambiguous and failed/incomplete responses. Prioritize merged/shared strips,
   same-pixel ambiguity, guard collection versus induced transients, and mixed
   photons from one decay. These categories come from different passes and must
   not be added as disjoint populations. Truth is isolated for posthoc evaluation.
2. Inspect original calibration outputs for already-saved full34channel responses.
   Export existing information when present. If genuinely absent, specify the
   missing calibration inputs and a bounded cost proposal for owner approval;
   do not manufacture templates or start new drift/injection calculations.
3. Freeze a small stratified development/holdout set separated by original event.
   Implement supported recovery and assess energy/position/sequence errors,
   false splitting and false pairing alongside recovered counts. Inspect the
   1332.49keV layer's19groups: per-group contributions to the peaks near(38,-2)
   and(46,18)mm, leave-one-group-out stability and bounded grid/iteration checks.
   These are local maxima, not an inferred count of Co60 sources. Reuse saved
   signals/candidates; no source-position input to reconstruction.
4. Only after the fixed acceptance passes, reprocess affected saved derivatives,
   update shared student processing and publish through the existing generator.
   Explain event use, waveform-to-cone reconstruction and joint energy/spatial
   results with readable uncertainty and traceable detail. Keep source count,
   isotope evidence and assumed plane distinct. No source-range claim from z40mm.

Acceptance is recovery with checked errors and no concealed regression, not a
larger accepted count or a prettier map. The measured old full-signal pass took
337.197s; new fitting/calibration costs are unmeasured and require bounded timing.
New Geant4, SSD drift, field solves, calibration injections and another1M are
outside this milestone. Review specific changes and reuse applicable checks;
no extra AI-review rounds. Apply AGENTS.md's direct product language and simple
implementation rules. Record current work in this plan and PROGRESS.md in place.

## Authorized milestone: saved-data GeGI corrections

Use the completed1M campaign to correct signal/readout/reconstruction, deliver
shared student software and replace the GitHub presentation. No new radiation,
SSD drift, fields, calibration injections or campaign. Automation stays PAUSED.
Existing originals and all failure/recovery evidence are permanent. The owner must
explicitly decide any future simulation after seeing this delivery and its limits.

The authorized saved-data implementation and delivery are complete: numerical
processing, student runtime release, generated website,731public-file byte checks
and actual desktop website verification. Remaining scientific limits are below;
they are not cleared by a functioning software pipeline. Use PROGRESS.md and
.local/autonomy/state.json for exact current artifacts. Do not restart completed
processing or source agents. Further calibration/simulation awaits owner decision.

## Implemented path and acceptance

1. Independently check the implemented nominal readout circuit against analytic
   charge-to-shaper response and fixed ADC gain. Preserve signed34channel native
   signals, charge/current accounting, raw IDs, zero/failed census and denominators.
   This is numerical verification, not a measured GeGI electronics calibration.
2. Use shared source/truth-blind waveform interpretation, bounded sparse X/Y energy
   allocations, independent saved depth templates and ambiguous sequence hypotheses.
   Remove strict2x2-interaction equivalence and last-crossing depth fallback. Preserve
   unresolved charge sharing, same-pixel multiplicity and cascade possibilities.
3. Check the independent bank against every original sealed request generation:
   exact model, serialized field cache, channels, native sources/environment and
   drift grid. Reused field precision differs from a fresh-solve precision request;
   the actual serialized cache identity controls compatibility. No bank => unknown
   depth/map. An admission-only source revision preserves the executed source and
   completed results without another full processing run.
4. Reconstruct finite-vertex conditional angular likelihood with candidate
   marginalization, unresolved mass and background. Do not normalize each cone's
   tiny in-frame tail to unity. Verify field-of-view overlap and coordinate/energy
   contracts. Known source positions are held-out evaluation only. Detector
   sensitivity/noise not calibrated from independent data must remain unknown.
5. Student Control uses the same shared processing, protected saved-input discovery,
   separate derivatives, chunk stop/resume and traceable original files. New
   standalone GeGI runs retain native-results.json and no longer generate source
   maps from the historical timing estimator. No canned campaign enters the ZIP.
6. Publish one pooled map with energy layers and clear signal-to-cone explanation.
   Keep the old708group control separate, with no claimed efficiency comparison.
   Assembly viewer uses214saved scored Ge segments; never call them full paths
   through unscored materials. Private slides are not uploaded. Old5000examples
   remain private and their former public entries redirect to the current result.
7. Build only through the maintained generator, verify tests and exact public
   runtime bytes, check live site and actual desktop pages, update this same handoff
   and push normally. Stop after this delivery; no automatic next simulation.

## Results that the delivery must not hide

57,613pulse groups reprocessed in337.197s,100sealed chunks,434conditionalgroups;
284came from39,683oldstrictrejects, but validatedrecoveries=0.426nativefailures are
retained.162groups/393candidates enter the shared measured-energy-window map.
Pooled assumedz40mm peaks lie near the two known positions, but the661.7keV layer
still misses the right source.1173keV has a secondary edge maximum;1332keV has only
19groups. Weightedmedian angularresidual22.162deg and33.22%masswithin15deg do not
establish detector resolution. Range/activity remainnull. Four acquisitions are
only two nuclides plus two monoenergetic gamma datasets at two positions.

Available saved injections retain selected X/Y waveforms, not the full34channel
response basis. Reliable neighbor-transient depth/substrip inference and multi-hit
separation need independent complete response data. Related strip-Ge papers guide
the architecture; proprietary GeGI hardware algorithms and measured calibration
are not available, so equivalence cannot be promised. Existing data cannot recover
unmeasured channels or identify every ambiguous interaction by software alone.

## Future work, only after an owner decision

First complete the independent34channel response/calibration and measured-noise/
crosstalk specification, then pass fixed blind signal/position/sequence acceptance.
Retain current failures as regressions; do not tune to known sources. A four-real-
nuclide design needs four explicit source positions and distinguishable gamma
spectra, consistent correlated decay handling and efficiency denominators. Directed
sampling must carry proper probability/weight accounting; do not independently
collimate decay daughters or claim isotropic efficiencies from unweighted cones.
Closer placement increases charge-processing load and near-field effects; it is
not automatically a net computational saving. Range needs an identifiable response
or external measurement, not an imposed plane or source-input echo.

No new cost pilot is authorized now. Historical sealed-stage compute was24.10h
(20.98hresponse/store,3.08htransport); failed attempts and development time are
excluded. Current saved-data processing cost is measured above. Costs/yields of a
changed four-nuclide geometry or full34channel calibration are unmeasured; establish
those with a bounded owner-approved acceptance before another1M.

Prior plans and milestones remain immutable in Git:
https://github.com/kunming-cn/END2END_Ge_Simulation/blob/47685df9f40a0b05e33d884bae85642a06fe87f3/tools/NEXT_DEVELOPMENT_PLAN.md
