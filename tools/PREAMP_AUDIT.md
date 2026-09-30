# Bounded preamplifier audit

Status: M3 equation/saved-waveform audit, 2026-09-29 (owner computer local date).
No numerical producer, scientific result, electronics setting or website plot was
modified. This verifies a declared ideal model and one saved example, not the
laboratory transfer function or arbitrary detector waveforms.

## Which waveform was inspected

The owner's screenshot uniquely matches AK02 **event 2** in the older
**100-primary/model, 662 keV mono-gamma pipeline demo**, run
`a288d2b165a74ee28d7f30e54b0bba1d`. It is not the million-decay native response.
The identifying shaped peak is 0.07290144046075923 V at 1084 ns.
The current `spectra/pipeline.html`, archived `examples/pipeline.html`, and
`examples/data.json` have the same event payload and waveform plot functions.
`tools/pipeline_explorer.html` plots saved `preamp_V` directly against `time_ns`.
There is no display sign inversion or absolute-value operation.

| Recorded quantity | Value |
|---|---:|
| Deposited energy | 148.80543821129578 keV |
| Final saved induced charge | 8.081107962476157 fC |
| Charge-grid spacing | 2 ns |
| Charge samples / endpoint | 49 / 96 ns |
| Numerical electronics samples / endpoint | 5049 / 10096 ns |
| Published display samples | 600 |
| Preamp minimum / time | -13.4659702633 mV / 94 ns |
| Preamp at saved endpoint | -11.0245629833 mV |
| Shaped maximum / time | +72.9014404608 mV / 1084 ns |

This event retains **`stopped_without_contact`**. Electronics acceptance does not
remove that charge-transport flag. Appending zero input current after the saved
charge endpoint is a model boundary condition, not proof of complete collection.

## Circuit and signs

`simulation/readout.jl` uses an ideal inverting charge-sensitive amplifier:

\[
C_f\frac{dV_p}{dt}+\frac{V_p}{R_f}=-I(t),\qquad \tau_f=R_f C_f.
\]

For short positive charge injection, the amplitude approaches `-Q/Cf`, followed
by exponential recovery. For finite collection, the current is integrated with
the feedback decay; the leading edge also depends on the current waveform.
The relevant charge-storage element is the **feedback capacitor**, not a detector
capacitor being charged to and discharged from the high bias after every event.
Opposite input/output polarity can give a positive jump and downward recovery.
The owner's positive oscilloscope pulse is not contradicted by the model sign;
the actual measurement node and transfer polarity have not been established.

The saved demo has `Cf = 0.6 pF`, `feedback_tau = 50 us`, matched pole-zero
compensation at 50 us, `shaping_tau = 0.5 us`, and shaping gain 20. An equivalent
ideal feedback resistance is 83.333 Mohm, derived from these parameters; it is NOT
a measured hardware resistance. Positive model charge produces negative preamp
voltage; the explicit `shaped = -gain*r2` makes the model's shaped pulse positive.
For an ideal delta injection with matched compensation, the shaper peaks at
`2*shaping_tau = 1 us`. Its finite-duration saved example peaks at 1.084 us.
Do not compare the shaped positive peak with the preamp tail as the same node.

## Why the plotted pulse looks different

The 10 us appended tail is **20 shaping constants**, but only **0.2 feedback
constants**. After charge input ends, its preamp retains `exp(-0.2) = 81.8731%`
of the endpoint amplitude. The displayed recovery is thus expected and incomplete;
the plot includes the whole saved window but not the whole physical-model decay.
For the same ideal decay, 250 us would leave about 0.674%. That is an analytic
prediction beyond the saved interval, NOT existing recorded waveform data.

All 49 charge-window samples, including the preamp minimum, survive display
decimation for this event. The 600-point display also retains the exact shaped maximum. The ~0.1 us leading edge occupies
less than 1% of the ~10 us-wide panel. No missing edge samples were found here.
The general display selector prioritizes charge/current features and the shaped
peak; it is not guaranteed to preserve every possible preamp extremum.
There is no recorded pretrigger or cross-event baseline history.

The model does not explicitly include the finite transistor bandwidth, input/
detector-capacitance-dependent rise and noise, a reset circuit, or scope coupling
and termination. `transport/experiment.json` DOES document LBNL Square/BF862/
nominal 0.6 pF, ORTEC 671/927 and Keysight DSOX3034A as laboratory inventory.
Exact per-run output node, polarity, feedback/reset details and scope settings
remain unverified. Nominal capacitance is not measured end-to-end gain.
Original measured AK02/SAP22 pulse files were not preserved.

## Numerical check and provenance

31 assertions passed using the unchanged actual `Readout` module: analytic delta
CSA/shaper response, rectangular-current integration, charge balance, zero and
opposite-sign inputs, amplitude scaling, grid refinement, and this saved event.

The comparison reconstructs equivalent-energy charge units from all 49 retained
charge-window samples, not from a spectrum or incomplete display waveform.
It is a one-event diagnostic, NOT a delivered general electronics-replay feature.
The old producer hash and current tested source hash differ and are retained
separately; no receipt was rebased. Recomputed preamp and shaped display voltages
agree to below 4e-17 V, and peak time and ADC code agree. Independent scalar CSA
integration also matches the saved samples and minimum. The test's voltage
acceptance bound was fixed at 1e-11 V before execution.

Evidence on the owner computer: `.local/preamp-audit-v1/`, including `input.json`,
`audit.jl`, `audit.log`, `audit-exit.json`, `numerical-audit.json`, independent
reviewer reports and the round completion receipt. No Geant4, SSD, field solve,
production campaign or laboratory fit was run.

## Disposition

No CSA sign, charge conversion, decay-exponent or screenshot plotting error was
found in this bounded audit. Do not globally invert or smooth the saved waveform.
A **presentation follow-up remains open**: leading-edge zoom, explicit feedback
constant and saved-endpoint labels, and clear preamp/shaper polarity descriptions.
Any longer tail must be a labelled newly calculated electronics derivative or an
explicit analytic illustration, never fabricated recorded samples. Real-hardware
polarity/bandwidth/reset choices require actual acquisition evidence and a new
configuration. General replay and full laboratory-waveform validation remain open.

Primary theory cross-check: [Mukhopadhyay et al., arXiv:2201.07410, sections 2
and Appendix A](https://arxiv.org/html/2201.07410v1), describes an inverting CSA,
integrating feedback capacitance, decay resistance and separate rise/decay time
constants. It concerns a silicon readout design; no hardware values from that
paper were imported as HPGe/LBNL calibration. The local findings above come from
the actual saved data, code and numerical audit, not that paper's apparatus.
