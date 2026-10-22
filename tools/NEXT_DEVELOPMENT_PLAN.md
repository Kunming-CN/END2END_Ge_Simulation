# Current development plan

## Active milestone — establish the GeGI full-chain reference, 2026-10-20

Owner explicitly resumed manual development on2026-10-22 after the completed
lateral-forward milestone. Native-cell forward validation and transport-only SSD
preselection assessment, fixed single/two-site inverse checks, region applicability
and fixedK1024optimization on one development event are complete. The transport-only
gamma-anchor prefilter has been tested and rejected. Explicit two-site selection
after reconstruction, the affected map and student release are complete. Exact153map-
group evaluation exposes sequence/vertex ambiguity despite matched charge-cell pairs.
Next distinguish descendant photons from independently emitted photons using the
saved ancestry ledger, then define the affected reconstruction test. Root owns
direction/quality; gpt-6.1-sol ultra implements small concrete changes without
speculative abstractions or repetitive checks/prose. Automatic monitoring stays
PAUSED; the old pause record is retained, not an active manual-work block.

Owner resumed evidence/planning after correcting the priority: establish a correct
small radiation -> charge ->34-channel signal ->readout ->reconstruction workflow
before recovery refinements and large samples. Automatic monitoring stays PAUSED.
Latest owner instruction "不需要每次等我审核，你继续就行" authorizes necessary
bounded small repair calculations, development and publication without per-round
approval. Preserve prior results/failures and measure costs; large campaigns stay
after full-chain validation, memory measured only, no resets.

The present chain is integrated, but its synthetic electronics and conditional
inverse model are not an identified GeGI instrument response. Existing numerical
circuit checks passed. Neither those checks nor low imaging acceptance locate all
remaining errors. First align observable definitions and localize the earliest
failed stage on the same saved events; do not tune a source map to known positions.

### Evidence-to-implementation map

| Stage | Physical/instrument evidence | Current saved implementation | Gap and next acceptance |
|---|---|---|---|
| Detector and radiation | PHDS current specification:90 mm diameter,11 mm thickness,32 strip elements [R1]. IAEA GeGI-4 report pp15-16 describes a different generation:10 mm thickness,16x16strips,5mm pitch/0.5mm gaps [R2]. | Exact versioned GeGI model; dedicated nominal cryostat. Livermore EM, Geant4 11.3.2/remage1.1.0; 0.1mm global/0.01mm sensitive production range cuts. Holder, contact/dead-layer detail and source capsule omitted. | Identify the apparatus/configuration used in the comparison. Reuse existing geometry and energy-ledger checks. Unknown passive material blocks absolute-efficiency claims; it is not a reason to rewrite the frozen geometry or restart transport. |
| Fields and carrier motion | Timing-to-depth depends on bias, impurity, temperature, geometry and readout [R3]. A related detector's fitted parameters cannot determine GeGI values. | Canonical92.3 K,−879V/0V, constant−5e9cm^-3, ADL2016/Bruyneel2016; reused Float32 field cache. Deterministic point charges,1ns steps,1000 ns limit; no diffusion/self-repulsion. | Distinguish observed spread from electron tracks versus omitted cloud diffusion. Preserve incomplete endpoints/charge; evaluate saved position/charge errors before proposing changed carrier physics. No retuning these inputs against the map. |
| Induced signals | Collection and neighbor transients carry different information; full multichannel signal bases are used in related segmented-Ge methods [R5]. | Campaign stores all34 signed native signals and deposition delays. Original calibration computed selected X/Y:2,727 signal records plus264 geometry exclusions. New original-grid bank retains full34 signals; original paths were not saved. | Original array/hash, polarity and charge/current checks are reusable. The original missing channels cannot be exported. Original-grid full-response reference and original-pair parity are complete; use the recorded responses without synthesizing missing templates. |
| Electronics and observable timing | Manufacturer describes32raw preamp outputs and an imaging/spectroscopy clock of50MSPS for current options [R1]. Exact generation/filter/firmware still needs matching. | Profile synthetic-signed-14bit-v1:ideal CSA Cf0.6pF, feedback/PZ50us, shaping0.5us, gain20,1mV threshold,14bit0–10V positive peak ADC.1ns is numerical integration. No measured noise/crosstalk or continuous baseline. | Highest-priority correspondence gap. Keep native charge, preamp, shaped peak, ADC energy and timing pickoff separate. Reuse analytic4-group/136-channel check (peak error<9.2e-14V, exactADC). It checks the nominal circuit, not actual GeGI filtering or hardware sampling. Do not set integration dt to20ns just from a clock specification. |
| Pulse grouping and spectroscopy | Same-decay gamma multiplicity and hardware coincidence/trigger selection must be represented consistently. The private July14slides distinguish full-detector, pixel-total and simulated-active-area spectra. | Decay pulses use100 us anchored half-open windows with reset electronics; no inter-primary pileup. Fixed calibrated collecting-channel sums include guards; X/Y are averaged. Noncollecting induced peaks are excluded. | First compare like-for-like spectra and event denominators. On the frozen 400-events, require exact old-energy preservation, then report Erec−Edep, bias/tails, face mismatch and missing/failure counts. Pulse-group energy is not necessarily one photon's incident energy. |
| Position, pairing and sequence | GeGI depth uses charge-arrival differences [R2]; calibrated timing/depth and separate energy/crosstalk/pairing stages are established in related work [R3, R4]. | Selected-pair native-waveform fits on0–250ns,0.25mm interpolated depths; ≤4strips/face,≤4sites,≤64hypotheses,2keV/2% compatibility. Charge pixels may differ from photon interactions. Same-pixel and cascade multiplicity unresolved. | Use fixed development/holdout events to quantify wrong/missingX/Ypairs, false splitting, matched position/depth error and sequence unknowns. Thresholds/tolerances are compatibility choices, not measured resolution. No promotion of conditional candidates unless these errors pass predefined, physically justified criteria. |
| Imaging and performance | Comparison requires the same sample selection, acquisition and normalization; source positions are independent evaluation only. |434 conditional groups; 162 selected map groups.1332.492 keV layer has19 groups / 58 sequences. Existing fitted-plane map uses z40mm and cannot measure range. | Reuse finished peak attribution: second mode loses a nearby maximum in3/19 leave-one-out runs; 40 iterations not converged under tested objective. Fix stage-level errors first. Map peak count/brightness is not source count, efficiency or validation. |

Source anchors: transport/gegi_source.py:287; scenarios/assets/gegi_cryostat_v1.json:8;
models/GeGI_3D.yaml:25; simulation/gegi_signal_helpers.jl:27;
simulation/gegi_response.jl:93,138,205; simulation/readout.jl:95,128;
transport/cs137.py:23; tools/gegi_campaign_response.py:53,89;
tools/gegi_signal_reconstruction.py:254,325,359. Preserve original generation pins.

### Current execution and acceptance

The frozen400-event evaluation and full saved signal-use export are complete; see
PROGRESS.md for exact denominators/errors and local evidence paths. No candidate
has been promoted to validated imaging. The original energy values are preserved.
Three development cases independently match the nominal circuit, exposing a
transient-to-positive-peak bias and a separate guard terminal-charge inconsistency.

1. Guard boundary diagnosis is complete on3saved paths: native coarse-grid
   interpolation explains the lost terminal charge. Forced contact1/0 substitution
   was rejected. Native local-grid solves for WP34(two levels) and WP17/20(level16)
   pass unchanged1e-6full-update gates; WP17/34 terminals match ideal collection and
   WP20's false terminal signal disappears while transients remain. See PROGRESS.md
   for exact costs, hashes and retained failed attempts. These3of34local potentials
   do not establish global field/waveform convergence. Do not patch production with
   only the corrected guards or rerun the same diagnostic.
   The existing fine-grid interpolation support is correct at all6captured endpoints.
   Saved WP34 readout differences are below the1.24558keV ADC step; equal ADC codes
   do not prove equal analog response or timing. No gates were tuned to this result.
   Dirichlet contact values follow the weighting-potential model[R6].
2. Use the owner's forward/inverse approach: validate interaction -> signed34-channel
   signal -> readout first, then infer positions/energies/multiplicity by explaining
   observed signals through that same response. Geant4 truth can establish/check
   response models in development; held-out reconstruction takes only observables,
   and known source positions remain independent image evaluation. Do not replace
   the inverse problem with source-position memorization or forced strip merging.
3. Address transient response in energy allocation. Independent per-strip positive
   ADC peaks need not equal final collected charge; adding these peaks can bias
   energy and pairing even when the nominal circuit is numerically correct. A
   new estimator must be explicit, preserve the original readout, use a fixed
   calibration and be tested on the frozen holdout without retuning its cuts.
4. The tested signal-use/software changes and aggregate diagnosis are delivered:
   student-runtime-1b88d5e7c2a7, website4466b8a,732live files verified. Further
   production changes require a validated forward response; diagnostic-only code
   does not require rebuilding unchanged student packages or website figures.

Continue authorized saved-data/software work without routine milestone approval.
Stop only for a concrete missing input or work outside the authorized bounded
full-chain repair. Do not request another per-round approval. The full34 basis and actual hardware transfer remain
separate requirements. No arbitrary resolution target or extra AI review rounds.

### Next saved-data milestone — full34 basis and joint signal fit

The original2991-record full34 bank is complete in223.531s:2727full responses,
264geometry exclusions;2551complete and176incomplete responses retain original
status.15completed pilot points were imported into18exact-coordinate checkpoints;
2709new drifts, no fields/transport. All2991selected-pair results/status/endpoints
and exact file hashes verified. Known complete endpoint identities match exactly;
face-sum roundoff3.05176e-5keV.216available pixels,40unavailable,175diagnostics.
Reuse calibration/full34-bank/results; full evidence and pins are in PROGRESS.md.
Do not rerun this bank or replace its original field with a partial local patch.

The all34 joint-fit mode is implemented and its18targeted tests pass; production
still defaults to selected_pair. It fits all signed channels including zero-terminal
neighbor transients, uses one observed ADC energy-flow scale, and applies the fixed
maximum-channel diagnostic envelope. No per-event truth gain, source-position fit,
or fabricated missing waveform. Sparse energy allocation/same-pixel multiplicity
and physical electronics identification remain explicit limits.

The first frozen200development comparison failed: candidate groups20->33 but
wrong pairs3/22->24/55. The total-energy residual scale hid weak collectors.
A targeted weighting correction restores positive-terminal scales for collectors,
retaining total-energy scales for neighbors; fixed gain and175diagnostic inputs
remain unchanged. V2development16.623s/95fits still does not improve the baseline:
20candidate groups,4/24wrong pairs; same39cells depthmedian .142586->.219220mm,
7improve/16worse/16tie. All200spectroscopy values are exact. Both failed versions
are retained in validation/full34-development and full34-development-v2.

The same-model objective diagnosis is complete:6minimax/aggregate tradeoffs and
7solutions worse on both metrics than known saved depths. Restored least-squares
optimization with separate max-channel acceptance;20targetedfit tests pass.
V3development improves shared46cell depthmedian .142586->.133164mm, but has
8/30wrong conditional pairs (best-RMS pair wrong3/24groups). No imaging promotion;
all200old spectroscopy values exact. Preserve all three derived versions.

The3case diagnosis is complete.720929 has an enumerated correct support rejected
by the waveform model; its worst cell is localized but off-center by .566/1.364mm.
727922 has nearly indistinguishable correct/wrong supports (RMS differs2.54%).
752677 needs five cells beyond the four-site cap, with rank-deficient energy
allocation. Sub-keV allocation differences in the first two cases do not establish
ADC bias as the dominant cause. Reuse saved support and cell-detail diagnostics.

Lateral response capture completed on all four candidate pixels {11,12}x{24,26}.
Fixed nine XY training offsets (-.4/0/.4 pitch)x11depths per pixel plus80 independent
positions (+/-.2 pitch each axis, five depths). Reuse44center responses, maximum
432new drifts/300s/one thread; original fields, no transport/field solve or retry.
All476complete in51.547s,44imports exact; endpoint/ideal-contact residual0.
All80independent points compared with no late activity or exclusions. Trilinear
max-channel RMS improves80/80 (median14.361->10.744keV), but pointwise maximum
error worsens64/80 (median40.377->59.974keV). Preserve this mixed result; no promotion.
Saved-waveform diagnosis localizes the increase to collector fronts, including
pureXY z0; neighbour RMS improves, all terminal errors0. One shared
34-channel time warp through training-predicted carrier arrival times was tested:
all80supported, max-channel RMS median9.734keV, max-point-error median35.986keV.
It improves64/ties16 versus spatial interpolation; pureXY z0 remains unchanged.
Collector RMS still worsens56/80 against centre-only, so the forward model is not
accepted for production. Retain all80comparisons and explicit order-crossing checks.
No validation arrival-time input, new physics, event-truth/source input or cut tuning.
Keep holdout unused and production selected_pair unchanged until an integrated
development result supports validation and release.

The Oct22four-corner test verifies interior/noncontact starts and identical electric
and all34weighting-grid axes. At one fixed independent500keV z0 target, using its
native-cell corners reduces max-channel RMS14.394344(centre)/10.614474(pitch)
to0.000522keV and max-point error36.124165/37.268822 to0.002200keV; terminals match.
Four new drifts took42.719s with no field solve. Reuse native-cell-pilot/results.
The same80fixed targets now have378completed native-grid-near supports,4imported
and374new drifts in44.843s. All80 improve against centre/pitch/old timewarp.
Max-channel RMS median1.499keV(max1.675), max-point-error median14.743keV(max16.933),
terminal error<=1.14e-13keV. Actual Float32 mm-to-m rounding is preserved in54corners;
actual-coordinate weights and60exact/20rounded target summaries are recorded.
The saved-only common-carrier timing comparison is complete: all80supported,
max-channel RMS median0.399042keV, max-point-error median/max1.63221/2.19316keV.
All64nonzero-depth cases improve; z0 changes are roundoff only. The existing
timewarp uses training endpoint times, not validation endpoints or real-event truth.

The saved-only inverse milestone is complete:80single-site inputs all select the
correct pixel,3Derror median/max0.010570/0.023088mm. Eight fixed equal-energy paired
mixtures select the nominal correct pairing, but two middle-depth cases are nearly
degenerate. Both competing matchings and all coarse hypotheses are retained.
These are ideal-charge sparse-domain results, not validated detector accuracy.
Exact source/input hashes, costs and targeted tests are in PROGRESS.md.

Saved real-event applicability is complete.720929 selects the correct support but
RMS12.1504keV and position errors0.9404/3.2749mm expose sparse-domain limits.
727922 has observable unmodeledY28/31/32 and four sites;752677 needs five. Neither
is recovered. The middle-depthcase3 pairing difference is comparable to saved
interpolation discrepancy. Preserve these results; no threshold/noise claim follows.

The contiguous interior region bank is complete:5148records,378unchanged imports+
4770new drifts,145.000s; no transport/fields/failures. All actual collectors match.
Eight points retain ideal-contact differences up to0.026642keV, without correction.
312contact-face starts remain omitted; no complete face/global convergence claim.
The first dense inverse retained1383840coarse alternatives across3410supported
cells (110carrier-order-flip cells unsupported).8-mixture parity passed.720929
keeps the correct pairing, RMS12.1504->2.75436keV and site errors0.312/0.603mm,
but its centroid-cell pair ranks240th and was pruned byK8. Preserve this result.
The fixed1024budget is complete:2032new+16reused refinements,69.181s, correct
pairing and RMS0.267866keV; site-centroid errors0.0073225/0.0515993mm, opposite
matching RMS93.1220keV. Result: `.local/gegi-10m/signal-recovery-v1/validation/native-region-720929-k1024/result.json`,
SHAa61c5c160c5f621c7676be660d82fe25406f779892b846de5e05ea93894f9e69.
The centroid-cell pair was refined; one Z-boundary site remains. No new physics,
Gram/parity rerun or holdout use. One development event is not validated recovery.

The requested pre-SSD study is complete: >2contributing gamma anchors would drop
14743of57613groups, including228of414groups with existing two-site candidates.
These are conditional signal-model comparisons, not measured hardware labels.
The owner agrees prefiltering is not practical here. Reject this rule, retain
zero-only skipping, and do not continue arbitrary multiplicity-cut searches.
The saved-imaging entry now supports explicit two-site selection after reconstruction,
preserving original priors, excluded ambiguity, IDs and all denominators;7tests pass.
Saved selection414groups/647candidates has map input153/287, including18/36 in the
1332.492keV layer. One changed-input map with the old settings is complete:7.876s
wall, no waveform fits or physics. Its1332.492keV peak positions remain(38,-2,40)
and(46,18,40)mm; removing longer candidate sequences did not remove the second mode.
Frozen candidate-pairing mismatches are0/15 and0/16, but sequencing and photon-vertex
identity remain unresolved. Wrong-order alternatives are not hard-choice errors.
Exact errors and counts are in PROGRESS.md and validation/two-site-output/result.json.
The changed runtime is delivered as student-runtime-bf951bf70627 with public bytes
verified. The waveform inverse remains a scoped development diagnostic.
Exact153map-group posthoc evaluation reused8prior metric rows and adds145supplemental
groups, never a new holdout. Endpoint pairing153/153; matched-cell median3D/depth/
absolute-energy errors1.412926mm/0.135299mm/0.366593keV. Strict sequence group classes
are1correct-only,35both,4wrong-only,113unknown-only. Multiple recorded photon trackIDs
explain83unknowns, shared-cell anchors29, strip-spanning anchor1. Distinct trackIDs
include secondary photons and cannot yet be interpreted as independent decay photons.
Next use the preserved ancestor links to distinguish these cases without changing
selection, thresholds or labels. Then assess whether a root-photon interaction
reference is supported by the saved records. Truth remains evaluation-only; no
truth-selected production map or pre-SSD filtering follows from this diagnosis.
The1332.492keV layer has2groups with both orders and16unknowns, so the two bright
spots cannot establish two sources. Exact evidence/retained failure in PROGRESS.md.

After this saved-data check, connect the same forward model to explicitly chosen
readout observables, then address variable site count and same-pixel ambiguity.
Do not choose raw34charge as if it were measured input. Owner-provided email from
Juergen Reichenbacher confirms ImagerPro exports single-site/two-site events as.bin;
multi-site events and waveforms are currently unavailable. BEGe3820waveforms are
offered for another detector and are not needed for the current GeGI interface.
Obtain an actual.bin sample, schema, units and software version before a parser.
The manufacturer manual gives processed DataStream fields with duplicate type1
and unspecified GlobalTime units; do not guess those definitions. Noomen's owner-
provided follow-up confirms corresponding N42 Full Detector/All Events,256pixel,
Pixel Total and32channel spectra. Their selected binary events reproduce the pixel
map well, but PHDS population definitions remain under discussion; no quantitative
agreement or common denominator is established. Prioritize a paired.bin/N42 sample
from the same acquisition and their selection settings: reproduce the pixel map,
then compare matching pixel/channel/total spectra. Do not assume that All Events,
Pixel Total and the binary1/2site populations coincide or sum channels as independent
deposited energies. All N42 products are cumulative histograms, with no per-event
XYZ or deposition energies; those are available only in single/two-site.bin records.
Measured positions are processed observables, not independent truth. Compare
simulation/measurement distributions, not individual unrelated events. Keep live/
real time and normalization explicit. Nominal-model
development continues with that limit explicit. Only after integrated development validation
may the frozen holdout support promotion/reprocessing and new public science figures.
Guard-field completeness remains the separate unresolved numerical stage above.
After current-plan validation, the owner's screenshot guides a website task using
actual reconstructed sky-direction Compton circles and summed intensity, or
correctly labeled cone intersections on a chosen plane. Not every plane intersection
is a circle. No fabricated cones, smoothing as validation or imagegen; no site/package
build in the present milestone.

Owner's efficiency suggestion was checked against all57,613saved groups. Zero-only
preselection already removes942,395primaries. Single-row/single-position cuts save0.
One recorded gamma-anchor cut covers29,875groups/29.13%ofpositive deposit rows,
but loses28,758accepted spectroscopy groups and4current conditional imaging groups.
Keep the existing default. Row-work fraction is not elapsed-time savings; any
future restricted imaging mode needs explicit selection and skipped identities.

A3saved-group benchmark confirms redundant unbounded readout before the retained
100us readout. Six timed evaluations:6.990s versus6.410s finite-only,8.30%electronics
time saved, final outputs deeply identical. Two groups had original finite windows;
the mono-gamma group's finite branch is explicitly counterfactual. No campaign
speedup inferred. The duplicate is now removed:68saved-electronics assertions,
74failure-policy assertions and6calibration-admission tests pass. Historical calibration
is retained through one proven exact source-pair bridge, with other identities strict.
The readout repair first shipped as cd31f32390d8 and is retained in bf951bf70627;
public bytes/latest link are verified. No science
rerun was needed, and no unrelated website-science regeneration is required.

### Reference scope and reuse

Private index: .local/gegi-10m/signal-recovery-v1/reference-index.json. It records
18 PPTs / 283 slides plus 4 targeted localPDFs, hashes and selected text. July 14 GeGI slides 3/4
plots were visually inspected; original source documents are read-only and private.
Slides3–5 separate measured spectra, normalized BP/SOE maps and a truth-selected
two-interaction demonstration. These are distinct validation targets. The February
strip deck contains toy/other-device studies and must not set GeGI parameters.
A focused three-deck check confirms that July14measured z is source placement,
not event depth; Sept24readout-chain figures are proposed/schematic; Oct27shaping
settings belong to the USD_9-14-18C_KM_Li_2501 hybrid detector, not GeGI. No indexed
owner-specific raw waveform export is established; the newer owner correspondence
above now defines the available processed.bin event classes.
The PHDS 2024 deck mainly concerns ring-contact detectors; the plant-imaging PhaseII
report concerns GIPR/coded aperture. Keep both out of GeGI electronics parameter
claims. The IAEA report's GeGI-4dimensions must not silently replace current11 mm.

- [R1 PHDS GeGI specifications and options](https://phdsco.com/products/gegi).
- R2 IAEA,2016Technology Demonstration Workshop on Gamma Imaging, external version
  2017-03-02, pp15–17; exact local PDF and hash in the private index. This is not
  automatically the manufacturer's separately linked2015workshop report.
- [R3 Rogers et al.,2026, per-pixel depth calibration](https://arxiv.org/html/2602.02442v1):
  SSD-to-readout timing calibration with measured distributions; COSI parameters
  and resolution figures are not GeGI values.
- [R4 Sleator et al.,2019, simulation benchmarking](https://arxiv.org/html/1911.02992v1):
  measured/simulated events share energy, crosstalk, pairing, depth and reconstruction.
- [R5 PHDS,2019, PAGe signal-basis development](https://science.osti.gov/-/media/np/pdf/sbir-sttr/SBIR-STTR-2019/Posters/Kiser_20190816-PixelArrayGermanium-Poster-MK-forWeb.pdf):
  related pixel detector, not evidence of GeGI's proprietary algorithm.
- [R6 SolidStateDetectors.jl, weighting potentials](https://juliaphysics.github.io/SolidStateDetectors.jl/main/man/weighting_potentials/):
  Laplace problem with selected-contact1/other-contact0; use the pinned installed
  SSD0.11.8 source for exact execution semantics, not the latest API documentation.
- [R7 POSEIDON final report, section5.2, p9](https://tuhat.helsinki.fi/ws/portalfiles/portal/379859820/POSEIDON_NKS_Final_Report.pdf):
  Helsinki used a90mm x11mm GeGI with16strips perface, strip list-mode data in20ns
  windows and a120ns coincidence selection for Cs137 Compton imaging. This supports
  a32-strip timestamp/charge observable contract, but does not specify raw-waveform
  availability, analog transfer, ADC resolution, guard readout or our unit's firmware.
  The120ns experimental coincidence cut is distinct from our100us decay grouping;
  do not substitute one for the other or infer a waveform sampler from timestamps.

The GeGI manufacturer manual is verified in the private reference-index.json,
SHAfc0647fcedeb19d52f73af5e8808f15941400a54b1a0227479ead06c1b9ebb0b.
Its processed DataStream schema does not resolve the duplicate type1 or GlobalTime
unit; the actual sample/version and matching electronics transfer remain needed.
Supervisor owns decisions; ordinary retrieval/development uses
6.1-sol, Astra only for necessary complex analysis. Reuse completed retrieval,
checks and publication. Completed bounded calculations include3original-deposit
path captures, local WP17/20/34solves and the original-grid full34 reference bank.
All are retained; current inverse-model diagnosis uses saved data only.

## Completed delivery retained

The 1M campaign, reconstruction-v3, student-runtime-1b88d5e7c2a7 and website
4466b8a remain the prior delivered baseline. PROGRESS.md contains their exact
receipts, hashes, tested scope and unresolved scientific limits. Do not rerun them
to resume this work. Earlier plans remain in Git at commit d94f82e.
