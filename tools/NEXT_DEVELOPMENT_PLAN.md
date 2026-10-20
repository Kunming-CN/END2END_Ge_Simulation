# Current development plan

## Active milestone — establish the GeGI full-chain reference, 2026-10-20

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
| Induced signals | Collection and neighbor transients carry different information; full multichannel signal bases are used in related segmented-Ge methods [R5]. | Campaign stores all34 signed native signals and deposition delays. Calibration computed only selected X/Y:2,727 signal records plus264 geometry exclusions; no full drift paths saved. | Original array/hash, polarity and charge/current checks are reusable. Full34 calibration is absent, not merely unexported. First measure which current candidate failures depend on missing neighbor response; do not synthesize missing templates. |
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

1. Saved endpoint query is complete: guard event723606's86contacts are correct,
   but geometric contact endpoints interpolate contact and noncontact grid nodes.
   ExactFloat32 endpoint algebra reproduces all34saved terminalvalues (0.0keVerror).
   Approved3row path capture c514ed87e5b0 is complete in37.343s. Same-path native
   replay matches all102waveforms bit-for-bit. Geometric Dirichlet1/0 assignment
   fails continuity (guard34:0.905912 just outside ->1 on contact), despite fixing
   terminal charge; do not apply it to production. Native XY spacing is1.17187mm,
   versus0.0375002mm in Z. Prepare a two-level localXY weighting-potential test on
   guard34 only, reusing original paths and unchanged Z/geometry/electric field.
   Original request83d4e680 was amended by the owner to remove memory gates;
   amended request218b4685 ran once. First-level5,744,640node solve returns
   max update3.5464764e-6 after55.326s, above fixed1e-6 acceptance; total77.031s.
   Pilot stops and preserves failure/field; second-level6,776,528nodes NOT run.
   Saved-state analysis reduces the3electron endpoint deficits8.38-9.41% to
   0-.4894%, without forcing contact values. This is an unconverged diagnostic.
   Approved continuation374f9bde ran once from the saved first grid: solve67.279s,
   total89.531s; returned1.1622906e-6>1e-6, second grid again NOT run. Do not
   weaken the gate or infer the exact native stop reason from incomplete logs.
   The strict local native-loop trace completed both grids under unchanged1e-6
   full-update gate: level8 300steps/19.241s and level16 5000steps/232.813s;
   combined275.984s. Exact inputs, fields, waveforms and history remain pinned.
   Level16 removes the three WP34 endpoint deficits without value substitution,
   but level16-level8 waveform maximum differences remain .126-.418keV.
   Next small complete check: propagate these saved signals through unchanged
   readout/timing and inspect whether the same grid gives correct boundary support
   for the opposite guard and noncollecting channels. Their old spurious terminal
   signals prohibit promoting a WP34-only patch to full34 production. Reuse native
   SSD and saved paths; bound any required channel solves, save resumable states.
   Do not repeat passed tests, old drifts, transport or unchanged publication.
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

### Conditional calibration option, not the first action

If saved-event diagnosis establishes the missing34-channel basis as the blocker,
the prepared bounded proposal is15 fixed 500 keV injections (3 pixels×5 depths), reuse
exact model/cache/environment, save all34 signed signals and explicit failures;
no new field solve or transport. Stop after15 attempts and measure startup,
per-injection time and bytes. Existing selected-pair bank call took158.298s;
an earlier cold startup took34.155s. These are historical two-channel timings,
not an estimate of full 34-channel cost. Full34cost remains unmeasured. The proposal is
recorded in signal-recovery-v1/calibration/inventory.json; latest bounded autonomy
covers it only if the identified blocker makes it necessary.
It would test template completeness, not establish hardware equivalence or resolve
omitted diffusion/noise. Do not launch it merely because this option is recorded.

### Reference scope and reuse

Private index: .local/gegi-10m/signal-recovery-v1/reference-index.json. It records
18 PPTs / 283 slides plus 4 targeted localPDFs, hashes and selected text. July 14 GeGI slides 3/4
plots were visually inspected; original source documents are read-only and private.
Slides3–5 separate measured spectra, normalized BP/SOE maps and a truth-selected
two-interaction demonstration. These are distinct validation targets. The February
strip deck contains toy/other-device studies and must not set GeGI parameters.
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

Complete GeGI operation/service manual and matching raw experimental electronics
configuration are still missing. Manufacturer datasheets do not supply the full
transfer function. Supervisor owns decisions; ordinary retrieval/development uses
6.1-sol, Astra only for necessary complex analysis. Reuse completed retrieval,
checks and publication. The only new physics in this continuation is the approved
3original-deposit drift capture; the subsequent boundary comparison uses saved paths.

## Completed delivery retained

The 1M campaign, reconstruction-v3, student-runtime-47685df9f40a and published
website remain the accepted prior delivery. PROGRESS.md contains their exact
receipts, hashes, tested scope and unresolved scientific limits. Do not rerun them
to resume this work. Earlier plans remain in Git at commit d94f82e.
