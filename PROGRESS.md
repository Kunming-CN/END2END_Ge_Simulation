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

Fixed1024candidate refinement per matching is complete on development event720929:
2032new+16reused refinements,69.181s, no new physics. Correct pairing; waveform
RMS2.754360->0.267866keV, site-centroid errors0.0073225/0.0515993mm; opposite
matching RMS93.1220keV. This is one ideal-charge development diagnostic, not
validated recovery. The optimization worker exited; overall project is incomplete.
The transport-only single/two-site prefilter study is complete and the tested rule
is rejected. On57613groups, >2gamma anchors would screen14743groups/679107positive
rows (47.67%row-work proxy), including228of414groups with existing two-site
imaging candidates. Those are conditional candidates, not measured hardware truth.
Seven targeted tests passed; the saved scan took40.475s with no physics/fitting.
Result: `validation/single-two-site-prefilter/result.json`, SHA
4c009b3321170346cf8e7a6695f7248150811562f36fe0c55112918e6a66b114.
All IDs, per-chunk decisions and denominators are retained. Unknown ancestry would
be kept; none occurred. Fixed development/holdout comparison did not tune the rule.
Owner agrees prefiltering is not practical here. Keep zero-only skipping.
The explicit two-site imaging option AFTER reconstruction is implemented and its
7targeted tests pass. `gegi_joint_imaging.py --reconstructed-directory --two-site-only`
preserves original priors, excluded ambiguity and all denominators; default behavior
is unchanged. Saved selection took4.630s:434groups/837candidates become414/647;
the map input162/393 becomes153/287, and1332.492keV19/58 becomes18/36.
Frozen200+200 evaluation: pairing mismatch0/15development and0/16holdout candidate
hypotheses; false splitting1/15 and0/16. Matched-cell median depth errors0.121431/
0.097902mm, absolute energy errors0.302211/0.401364keV. Candidate sequence labels
correct/wrong/unknown are2/2/21 and2/6/17; these are alternatives, not hard-choice
error rates. The two known development groups each retain both orders. Charge cells
are not proven photon vertices. No additional recovery is validated.
Evidence:`validation/two-site-output/result.json`, SHA
2a54be02d09a57ab2d314864b4f199bb0e4b4dac01d72864e16695448a8d326f.
The changed map was computed once with the same40iteration,z40mm settings and no
plane profiling:7.876s wall/2.047s map+checks.1332.492keV retains peaks at(38,-2,40)
and(46,18,40)mm; no convergence claim or new leave-one-out study. Report SHA
bc6c4d33db93b96f066eb86df6c79a2a0cd540870e10296ab350642ee3a1e59d.
Map comparison SHA9ca6b42833682905e6b41d19653575a5e1bc47423c3ac5fd1cf1bb2e78e9eb8c.
Only8frozen400groups intersect the153mapgroups (6development/2holdout); all4holdout
wrong-only groups lie outside the existing map energy windows. No escape mechanism
is inferred from that. Exact153map-group posthoc evaluation is now complete:
153metadata reads,8prior metric rows reused,145supplemental evaluations (not a new
holdout). All153conditional hypotheses match the endpoint-cell pairs; anchor-count
false splitting0. Across306matched cells, median3D/depth/absolute-energy errors
are1.412926mm/0.135299mm/0.366593keV. Photon-vertex error is separately available
for80sites in40groups: median1.424950mm; it is not the charge-centroid error.
Strict order classes:1correct-only,35both orders,4wrong-only,113unknown-only.
Candidate labels36correct/39wrong/212unknown are alternatives, not hard-choice
error rates. Unknown groups:83multiple recorded photon trackIDs,29shared-cell
anchors,1anchor spanning strips. Secondary photons also have distinct trackIDs;
this does not yet establish multiple independent emitted photons.
1332.492keV has18groups:2both orders,16unknown (13multiple-track,3shared-cell).
Saved ancestry resolves152/153groups to one earliest gamma lineage, including82of
the83multiple-track groups; no missing parents/cycles.1332.492keV has17single-lineage
groups and one two-lineage group995246. Secondary phot/eBrem processes explain most
new photon IDs. Preserve the old strict labels; unknown does not mean invalid.
Lineage evidence:`validation/two-site-map-evaluation/continued/lineage-summary.json`,
SHA4c2f203c341b0d6f286a4c0e899b500c6e69c424d531dcd07cd4791c211281bc;
bound reproduction code is beside it. Parent-gamma reference is now complete:
row ancestry maps to the first recorded child birth under the earliest gamma;
birthXYZ/time/process define each interaction.82groups have two dominant uniquely
mapped interactions (2correct-only,75both orders,5wrong-only);71remain unknown
(66not exactly2dominant interactions,4cell ambiguity,1two roots).1/5keV sensitivity
gives the same reference count. All407direct-root gamma rows remain explicitly
unassigned to interactions: median/max per-group energy0.19441/0.51656keV.
No identity conflicts; root/interaction energy closure errors<=9.10e-13keV.
Three targeted tests passed;3cached+150new metadata reads,1.738s wall. No waves,
fits, maps or physics. Result:`validation/root-gamma-interaction/evaluation/result.json`,
SHAd4aeb98b66a7fc7a6e87096cfa57deec2f1ee9459dd3fa256d89046039093a69.
Root birth energy is not detector-entry energy; two dominant interactions do not
prove full absorption. Old strict labels and all reconstruction inputs are intact.
Four old wrong-only groups are excluded by cos(theta)<-1, not coincident positions;
diagnosis SHA4e8a2f311b27ae021f59ea9a72dd6086761b07033a895a8d9a072fbc319a244e
(`two-site-map-evaluation/continued/wrong-order-diagnosis.json`). Three have Ge
deposition below root birth energy:879908/906665/913963.235273 and newly identified
278717 both deposit their662keV root energy, so these two need targeted transport-
versus-free-electron-kinematics diagnosis before changing any reconstruction cut.
No noise, escape or Doppler mechanism is asserted from these counts alone.
Evidence:`validation/two-site-map-evaluation/continued/result.json`, SHA
20035307ef632c8259805c5ac8adb47a031f41230897a14e6fdaf0b28b76fca0.
An initial5.819sattempt stopped at102groups on a progress-file replacement error;
the closed checkpoint and failed source remain. A targeted continuation read only
the remaining51metadata records in5.206s wall/4.932s internal. Two boundary tests
passed; no physics, waveform fits or maps. Student release is complete below;
website figures await reconstruction validation. The inverse remains diagnostic.

Hardware correspondence: the July14 GeGI slides show measured spectra/maps, not
raw strip-energy/time or waveform export definitions. Its simulated interaction
positions and assumed/physical source depths are not measured event DOI. Sept24
chain slides are schematic; Oct27 hybrid-detector shaping settings are not GeGI.
Owner-provided email from Juergen Reichenbacher establishes that GeGI ImagerPro
currently records only single-site and two-site events as.bin; multi-site events
and waveforms are unavailable. Offered BEGe3820waveforms are a different detector
and are not needed for this GeGI interface. Actual.bin sample/schema/units and
software version remain needed. The verified manufacturer manual describes a
processed DataStream schema, but duplicates type1 and leaves GlobalTime units
unspecified; do not implement a guessed parser. Private reference-index SHA
fc0647fcedeb19d52f73af5e8808f15941400a54b1a0227479ead06c1b9ebb0b.
Root handles the concise reply draft; no email was sent. Do not infer waveform
sampling from a50MSPS clock specification.
Noomen's follow-up confirms paired N42 products: Full Detector/All Events,256pixel
spectra/Pixel Total, and32channel spectra. Their binary-selected pixel map agrees
well by their report; exact population/selection definitions are pending PHDS.
All N42 products are cumulative histograms without individual-event XYZ or
deposited-energy records; event-level information exists only for.bin single/two
site records. Experimental reconstructed coordinates are not independent truth,
and measured/simulated events are compared statistically, not paired one-to-one.
Next experimental input is a matched.bin/N42 acquisition plus selection/settings,
not BEGe waveforms. Verify map reproduction before comparing matched spectral
populations; do not assume all totals share a denominator. No sample is received yet.

After current-plan validation, publish actual reconstructed sky-direction Compton
circles with summed intensity, or correctly labeled cone intersections on a chosen
plane, following the owner's screenshot. Plane intersections are not always
circles. This is a sequenced presentation task: no fabricated cones or smoothing
as validation. No site/package build is part of this record delivery.

## Latest tested software and public delivery

Finite-window GeGI readout now runs once through a shared channel helper. Native
signals, final electronics outputs and group metadata remain identical on the
saved regression.68electronics and74failure-policy assertions plus6calibration
admission tests passed. Historical calibration reuse admits only one exact proven
old/new G-source pair; other native/environment/model/field pins remain strict.
Evidence: `signal-recovery-v1/validation/readout-single-pass/validation.json`,
SHA1d13ac42d4506318edc2038121f2a8709da7375e499084c66b7f94622836ec96.
No transport, drift, field or calibration calls were used for this repair.

Latest source/runtime commit `bf951bf70627447d13301c4a746cc570224a3ba8` is pushed.
Student release `student-runtime-bf951bf70627`:896097bytes/187members, SHA256
`7a58fe67c3ff9fa8367d80071d4df8c254c00167d160c5675c34726d29accefa`.
It adds the optional two-site saved-imaging CLI and retains the prior readout fix.
Five package tests passed6.594s; build2.507s. Public versioned/latest assets, embedded commit, receipt,
remote tag/main and actual public-guide download link verified. Developer inverse
prototypes are excluded. Authority: `.local/student-runtime-p1/COMPLETE.json`.
No installation or scientific rerun; current ZIP only, compact previous delivery retained.
Delivery receipt SHA8f5f8bf0323af8e9abed69e3b8b283f61cf5f3d0bcaf971bfeda450939139d22.

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

- Interior region bank: `calibration/native-region-bank`,5148completed records,
  378unchanged-payload imports+4770new drifts in145.000s, no failures/fields/transport.
  All175032signals/10296contact endpoints verified, actual collectors all match.
  Native endpoint algebra0;8points retain ideal-contact deviations up to0.026642keV,
  uncorrected. Native internal28.126s; capture/store/diagnostics74.018s; saved-file
  verification34.698s.312contact-face starts omitted;4719exact/429rounded points,
  maximum1ULP. COMPLETE SHA
  `2a6f723eb9c93a92e4029bbc7112c15bae7c05e80e9109ddd6c6bdbebdf3fab1`,
  summary SHA8bc72dbc95097a103e9e8336b44cc4ff212ad115169a3946d6daa2f215e39068.
  Region defined by observed strip geometry, not event truth. Julia exited.

- Dense region inversion: `validation/native-region-720929/result.json`,
  SHA02716a816be3c70cfb0bf27fcf9a5f3dc81d6efe93841a841542e3418837e0ac.
  3410supported/110carrier-order-flip cells;1383840coarse alternatives saved
  losslessly. Eight-mixture/all-coarse parity passed4.711s, no physics.
  Correct pairing; RMS12.1504->2.75436keV; max-channel RMS11.40534keV.
  Site centroid errors0.312386/0.602666mm, energy+0.152881/-0.087176keV.
  Both sites hit cell boundaries. True centroid cells now supported, but their
  pair ranks240th, outsideK8. Search0.828s, load24.399s, prep1.859s, store1.607s;
  total42.440s includes reporting pause. A pre-fit loader provenance bug/failure
  was retained and fixed; prior8-fit parity and physics were not repeated.

- FixedK1024 optimization: `validation/native-region-720929-k1024/result.json`,
  SHAa61c5c160c5f621c7676be660d82fe25406f779892b846de5e05ea93894f9e69.
  Reuses1383840coarse alternatives and16pinned refinements;2032new give2048total,
  exactly1024per matching in69.181s. RMS0.267866keV versusK8's2.754360keV;
  opposite matching93.1220keV. Site centroid errors0.0073225/0.0515993mm,
  energy errors-0.0807374/-0.0426575keV; one Z-boundary site remains. The true
  centroid-cell pair was refined. No Gram/parity/physics rerun; checkpointed
  candidates and the pre-refinement arithmetic-admission failure are retained.
  One development event only; no global-optimum, hardware or validated-recovery claim.

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
