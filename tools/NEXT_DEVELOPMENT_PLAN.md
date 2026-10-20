# Current development plan

## Authorized milestone: saved-data GeGI corrections

Use the completed1M campaign to correct signal/readout/reconstruction, deliver
shared student software and replace the GitHub presentation. No new radiation,
SSD drift, fields, calibration injections or campaign. Automation stays PAUSED.
Existing originals and all failure/recovery evidence are permanent. The owner must
explicitly decide any future simulation after seeing this delivery and its limits.

The numerical implementation, saved-data processing, student integration and runtime
release are complete. Final website generation/live verification and Git handoff
are the remaining work. Use PROGRESS.md and .local/autonomy/state.json for exact
current artifacts. Do not restart already completed processing or source agents.

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
