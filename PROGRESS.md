# Current handoff

## Active work — 2026-10-22

Owner requires continuous development until a concrete decision is needed. Root owns
scientific direction; ordinary implementation uses gpt-6.1-sol ultra. No additional
AI review. Monitoring remains PAUSED, no resets or large campaign. Necessary small
repair calculations are authorized, bounded, measured and restartable.

Same supervisor owns `.local/autonomy/gegi-saved-recovery.lock`; prior ownership
and pause records retained. Actual process/Git inspection preceded continuation.
Current state is `.local/autonomy/state.json`. Do not start a second supervisor.
Detailed preceding handoff is preserved in Git at
[cd31f32390d8](https://github.com/Kunming-CN/END2END_Ge_Simulation/blob/cd31f32390d8724d5ca17ff44cbb6bd23ff1b8f8/PROGRESS.md).
All local scientific originals and failed attempts remain permanent.

Current task: capture the geometry-defined contiguous interior native-grid region
for observed stripsX11/12 xY24/26, then reevaluate group720929 with the same fixed
waveform-only two-site search.5148interior corners:378imports+4770new, one thread,
300s worker cap; original fields, no transport/field solves.312contact-face nodes
excluded explicitly. Preserve mixed-collector/boundary/partial responses; they are
not automatically valid interpolation cells. No holdout or imaging promotion.
Region fitter retains all coarse costs losslessly and fixed8refinements per matching.

Hardware correspondence: the July14 GeGI slides show measured spectra/maps, not
raw strip-energy/time or waveform export definitions. Its simulated interaction
positions and assumed/physical source depths are not measured event DOI. Sept24
chain slides are schematic; Oct27 hybrid-detector shaping settings are not GeGI.
Owner says the detector is at SDSMT; raw details may need Noomen. A short request
email was drafted, not sent. Raw format remains unknown; nominal-model work continues. Do not infer waveform sampling from a50MSPS clock specification.

## Latest tested software and public delivery

Finite-window GeGI readout now runs once through a shared channel helper. Native
signals, final electronics outputs and group metadata remain identical on the
saved regression.68electronics and74failure-policy assertions plus6calibration
admission tests passed. Historical calibration reuse admits only one exact proven
old/new G-source pair; other native/environment/model/field pins remain strict.
Evidence: `signal-recovery-v1/validation/readout-single-pass/validation.json`,
SHA1d13ac42d4506318edc2038121f2a8709da7375e499084c66b7f94622836ec96.
No transport, drift, field or calibration calls were used for this repair.

Source commit `cd31f32390d8724d5ca17ff44cbb6bd23ff1b8f8` is pushed. Latest student
release `student-runtime-cd31f32390d8`:895444bytes/187members, SHA256
`7abfbca8f013202398d04123e8208e28c46cc0158537066fffb6dbeacc41a17e`.
Five package tests passed. Public versioned/latest assets, embedded commit, receipt,
remote tag/main and actual public-guide download link verified. Developer inverse
prototypes are excluded. Authority: `.local/student-runtime-p1/COMPLETE.json`.
No installation or scientific rerun; current ZIP only, compact previous delivery retained.

Website content is unchanged by this readout repair; its latest-download link serves
the new verified software. Prior homepage delivery `044eaae02a674a8ad5e996f24a4a28b374ad435d`
is complete: build `14090ab9454b0c088785e33080308e27b488ee94982694c5f15878f55175903e`,
109pages/3505links,975live artifacts verified, desktop/mobile checks. Receipt:
`.local/site-audit-20261022/homepage.json`. Do not rebuild or retest unchanged site
science solely to resume work. New scientific figures require validated results
and normal build_site/test_site/check_site/live checks; never hand-edit docs.

## Saved native response and inverse evidence

All paths below are under `.local/gegi-10m/signal-recovery-v1/`.

- Original-grid full34 bank: `calibration/full34-bank/results`,2991records:
  2727responses (2551complete/176incomplete) and264geometry exclusions.2709new
  drifts223.531s; original selected-pair values/status/endpoints exactly preserved.
  216pixels available,40unavailable. Original missing channels could not be exported.
- Lateral references: `calibration/full34-lateral-pilot/results`,476complete,
  44imports+432new drifts51.547s;396training+80independent validation positions,
  four pixels {11,12}x{24,26}. Old pitch interpolation/timewarp left large front errors.
- Native-cell bank: `calibration/native-cell-bank`,378complete supports,
  4imports+374new drifts44.843s; no transport/fields. COMPLETE SHA
  `9558d3533446380a82667cd8ad6dfec0fe0d12442553d97e42e8201ee787de73`.
  All endpoint identities/ideal-contact differences0.54corners retain a recorded
  -1ULP X-coordinate offset through the unchanged Float32 mm interface; actual
  coordinates determine weights.324exact corners;60exact/20rounded validation cases.
- Saved common-carrier timewarp: all80supported, max-channel RMS median0.399042keV;
  maximum point error median/max1.63221/2.19316keV. Terminal differences<=1.14e-13keV.
  Uses training arrival times only. `results/timing-comparison.json`,
  SHA953a45ade227f2d2fa290c66de282fd05ed2290a41590cdd3a7bc204f1ef787c.
- Single-site inverse: `validation/native-inverse-single-site/result.json`,
  SHA5184c58e8b80d56241b4abd11a86f2d74c17d0b671832700adfe00f8dbabe23a.
  Each80waveforms searches all80cells/4pixels; waveform+training bank only.
  80/80pixels correct,0unsupported/boundary.3Derror median/max0.010570/0.023088mm;
  absolute energy error0.025188/0.102807keV.35.339s with4pilot fits reused.
  Three targeted tests include independent317keV gain and truth isolation.
- Two-site inverse: `validation/native-inverse-pair/result.json`,
  SHAaeb714087bd816e59d04b540e9ff98c5f44823384ecfe46d7ffc9fb393acc903.
  Eight fixed equal-energy prompt mixtures;800coarse hypotheses,8refinements per
  matching. Nominal8/8pairings correct.16site position errors median/max
  0.013053/0.023088mm; absolute energy0.020678/0.056917keV.3.902s with2pilot fits
  reused;4targeted tests. Cases3/7 near-degenerate between matchings. No claim of
  robust hardware discrimination, global optimum, false splitting or same-pixel
  multiplicity. Both inverse tools are ideal-charge sparse-domain diagnostics.

- Saved real-event applicability: `validation/native-inverse-applicability/result.json`,
  SHAa019a603b00c4656c4365825f01ff896f839c304877d67274a942373b9ef81d3.
  720929 selects correct pairing but waveform RMS12.1504keV, position errors
  0.9404/3.2749mm; both sites hit sparse-domain boundaries.727922 has observed
  unmodeled Y28/31/32 and four truth cells; RMS176.4474keV, not recovered.752677
  not fitted. A downstream CRLF parsing failure is retained; continuation reused
  the completed720929 fit. Total two fits, no physics; continuation2.020s.
  z0case3 opposite-pairing max-channel separation0.004412keV is comparable to
  saved interpolation residual0.005749keV; case7 is larger (0.053296/0.006295keV).
  These are deterministic discrepancies, not noise estimates or acceptance cuts.

Reuse frozen tools/results; no need to repeat these calibrations or fit checks.
Code source hashes and complete input bindings are in the corresponding receipts.

## Original campaign and failed recovery attempts

`.local/gegi-10m/campaign` is complete:1Minitial primaries/100chunks,400kgammas+
600kdecays;2400preparation primaries excluded.942395zero primaries were already
skipped downstream;57605nonzero primaries produce57613pulse groups.
434conditional groups/837cones; current map162groups/393candidates. These are
not validated detector efficiency.1896incomplete groups include426native failures.
Keep all original identities, null/failure accounting and raw results unchanged.

Latest corrected baseline `.local/gegi-10m/reconstruction-v3`; saved-use-v2 counts:
55591spectroscopy groups (55157spectroscopy-only),434conditional,1896incomplete,
126unresolved. Old reconstructed energies exactly preserved. Frozen400events split
200development/200holdout by event. Baseline wrong pairings dev3/22,holdout5/24;
false splits1/22,2/24; depth median errors0.143/0.100mm.

Full34 v1/v2/v3 development attempts failed promotion and remain retained. V3:
24groups/30hypotheses,8wrong pairs/1false split; best-RMS choice wrong3/24groups.
Three-case diagnosis:720929 correct support rejected by off-centre waveform model;
727922 nearly tied supports;752677 five cells/rank-deficient energy allocation.
No source-position/true-interaction information may enter reconstruction.

1332.492keV double-peak attribution is complete:19groups/58sequences; secondary
peak loses nearby maximum in3/19leave-one-out runs.40iterations not converged under
tested objective. Reuse evidence; do not infer two sources or tune to true positions.

## Remaining physical boundaries and compute findings

Original fields are reused, not solved per event:100native receipts report no new
field solves; five resident loads totaled160.649s. Original cache SHA
`f75280e7f21b1a1a06c2a6623aed62873065ca72db02bb1f93a61b9b853b90e8`.
SSD0.11.8/Julia1.13Float32,92.3K,-879/0V,-5e9cm^-3,ADL/Bruyneel,1ns/max1000steps;
no diffusion/self-repulsion. Do not silently alter canonical model/fields/physics.

Guard diagnosis on3saved paths identifies coarse weighting-grid interpolation.
Local WP17/20/34refinements passed unchanged1e-6full-update gates and corrected
terminal inconsistencies; all original paths/waves and failed solves remain.
A forced endpoint1/0 patch was rejected. These three potentials do not establish
all34/global convergence and must not be spliced into production as a full repair.

Synthetic readout numerical checks pass, but actual GeGI transfer/filter/noise,
ADC, timing extraction and guard observability remain unidentified. Keep native
charge, preamp, shaped peak and ADC energy distinct. Neighbor positive peaks can
bias energy allocations. Same-pixel/multi-photon multiplicity and multi-deposit
charge topology need explicit support; a running pipeline is not experimental validation.

The requested transport preselection study is complete on all57613groups:
single-row/single-position cuts save0. One-gamma-anchor restriction retains29875
groups/29.13%positive-row work proxy, but loses28758accepted spectroscopy groups
and4conditional imaging groups. Default remains zero-only. Evidence:
`validation/transport-prefilter-feasibility.json`,SHAbab9e90b...45ac1ffb.

Saved electronics benchmark:3groups x2repeats,6.990s->6.410s (8.30%), exact final
outputs. One finite-window case is counterfactual. This is electronics-only timing,
not whole-campaign speedup. Evidence:`validation/readout-duplicate-benchmark/result.json`,
SHA098be9b3...b6bc60d. Prior aggregate native/drift/readout/IO75541.740s and transport
driver11102.995s are stage totals, not pure SSD or Geant4 measurements.

Read `tools/NEXT_DEVELOPMENT_PLAN.md` for the scientific queue and source map.
Private PPT/PDF index:`signal-recovery-v1/reference-index.json`; primary references
R1-R7 are in that plan. Keep user inputs private, originals/failures permanent,
and public wording direct. Large samples follow a correct small full-chain workflow.
