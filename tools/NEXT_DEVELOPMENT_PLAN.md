# Current development plan

## Active milestone — establish the GeGI full-chain reference, 2026-10-20

Owner resumed evidence/planning after correcting the priority: establish a correct
small radiation -> charge ->34-channel signal ->readout ->reconstruction workflow
before recovery refinements and large samples. Automatic monitoring stays PAUSED.
No new transport, drift, field solve or calibration calculation is authorized.

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

### Next bounded execution and stop condition

1. Reuse the frozen 400-event manifest (200 development/200 holdout, original-event
   separation) and original readout/native stores. Finish the existing evaluation
   without changing reconstruction or selection. Report stage quantities and
   wrong-pair/splitting/position/sequence errors, separating unknown truth matches.
   No complete campaign fit, new injection or physics run is needed for this step.
2. From those errors select the earliest concrete failure and one repair. If the
   failure is an implementation defect, correct and test that path. If it is an
   unidentified hardware response or missing calibration, specify the required
   input/computation before proceeding; do not substitute a plausible instrument.
3. Freeze an integrated small-case acceptance before processing affected saved
   derivatives. Require identity/unit/sign/energy bookkeeping, explicit failures,
   no truth leakage, exact fixed-gain preservation and held-out error accounting.
   Numerical tolerances use existing analytic/quantization bounds; physical energy,
   position and timing criteria must come from matching data/specification. Do not
   invent an arbitrary resolution target to declare success.
4. Only after this acceptance update student software and publish relevant results.
   Large-sample radiation is a later decision based on residual statistical need.

Stop this milestone once the evidence map and next diagnostic are concrete; do not
expand into a literature survey or another general review. The planning/evidence
map above is complete. The400-event evaluation is the next execution milestone;
its manifest already exists, but no completed evaluation result exists yet.

### Conditional calibration option, not yet authorized or first action

If saved-event diagnosis establishes the missing34-channel basis as the blocker,
the prepared bounded proposal is15 fixed 500 keV injections (3 pixels×5 depths), reuse
exact model/cache/environment, save all34 signed signals and explicit failures;
no new field solve or transport. Stop after15 attempts and measure startup,
per-injection time and bytes. Existing selected-pair bank call took158.298s;
an earlier cold startup took34.155s. These are historical two-channel timings,
not an estimate of full 34-channel cost. Full34cost remains unmeasured. The proposal is
recorded in signal-recovery-v1/calibration/inventory.json and requires owner approval.
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

Complete GeGI operation/service manual and matching raw experimental electronics
configuration are still missing. Manufacturer datasheets do not supply the full
transfer function. Supervisor owns decisions; ordinary retrieval/development uses
6.1-sol, Astra only for necessary complex analysis. This milestone used one
read-only 6.1-sol source-mapping task, reused old checks, and ran no new physics,
calibration, reconstruction fit or whole-campaign processing.

## Completed delivery retained

The 1M campaign, reconstruction-v3, student-runtime-47685df9f40a and published
website remain the accepted prior delivery. PROGRESS.md contains their exact
receipts, hashes, tested scope and unresolved scientific limits. Do not rerun them
to resume this work. Earlier plans remain in Git at commit d94f82e.
