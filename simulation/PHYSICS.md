# Physics basis, evidence and validation boundaries

This is the shared method/reference map, not a second development plan. See
[PROGRESS.md](../PROGRESS.md) for measured results and [README.md](README.md) for commands.
Canonical AK02/SAP22 configurations remain snapshots, not newly fitted models.

## Signal and transport layers

Geant4/remage supplies radiation deposits. SSD supplies charge transport and the
signed electrode signal. Electronics subsequently maps current to measured
voltage and ADC values. Preserve raw event/step identity and deposition time.
For a created electron-hole pair at one point, the no-trapping final signal in
the repository convention is proportional to W(hole endpoint) - W(electron
endpoint); the identical initial terms cancel. Near-unit induced charge therefore
does not prove that both carriers reached geometrical metal contacts.

The low-field approximation v = +/-mu E and the Einstein relation D = mu k_B T/q
are model assumptions with domains of validity. Our pinned AK02 inactive-layer
model includes impurity/phonon mobility but not a fully calibrated anisotropic,
velocity-saturated bulk model. [Zhang et al. (2026)](https://doi.org/10.1140/epjc/s10052-026-15508-3)
explicitly discusses this limitation and implements the three-region method in SSD.
Its fitted lifetime for another detector must not become an AK02 measurement.
[Dai et al. (2023)](https://doi.org/10.1016/j.apradiso.2022.110638)
provides a complementary transport/CCE reference ([preprint](https://arxiv.org/abs/2207.11902)).

## Boundaries that must not be conflated

A donor/acceptor compensation position, electrical depletion boundary, and full
charge-collection depth are different quantities. The last also depends on the
response definition and carrier losses. A discontinuous no-diffusion response
can move when grid nodes change; a large fixed-point difference alone is not a
global event-energy error. Report actual ticks and E/W profiles rather than
calling a minimum spacing parameter the grid resolution.

The AK02 diagnostic records fields at reporting thresholds without clipping
small fields to zero. Capped or unresolved trajectories remain flagged. A
cross-weighting calculation on frozen endpoints isolates changes in the weighting
solution, including its depletion/permittivity representation; it does not isolate
interpolation alone and is not a self-consistent hybrid detector prediction.

## Diffusion: tested limit versus unresolved physical closure

Uniform coefficients imply per-axis variance 2Dt and zero cross-covariance.
`validate_transition.jl --phase mobility` freezes coefficients from the actual
AK02 mobility class in disposable homogeneous test models. Full-hop, duration,
boundary-clearance and prospectively fixed statistical guards test that numerical
limit. They do not validate a spatially varying Li profile or surface recombination.
The test uses numerical parcels, not a literal population of independent carriers
with a measured cloud size. Self-repulsion is disabled.

For smooth scalar D(x), pre-step local random-walk coefficients have the Itô
continuum form dX = v dt + sqrt(2D) dB, whose density equation contains
`-div(v n) + laplacian(D n)`. A Fick constitutive flux `J = v n - D grad(n)`
instead requires the Itô drift `v + grad(D)`. These expressions coincide when D
is constant. This mathematical distinction is an interpretation question, not
proof of an SSD defect: Dai's discrete departure-site diffusion rates also need
to be reconciled with the intended continuum law. No gradient correction is
silently added to the pinned package. Before variable-D calibration, state the
carrier-density convention, equilibrium assumptions, transport law and boundaries.
Pinned implementation: SSD 0.11.8 `ChargeDrift/ChargeDrift.jl` and
`ChargeDriftModels/InactiveLayerChargeDriftModel/InactiveLayerChargeDriftModel.jl`.

## Neutral-region weighting and finite conductivity

SSD's experimental large-permittivity treatment of undepleted regions is not a
measurement of conductivity. A screening estimate is sigma = q(mu_e n_e + mu_h n_h)
and tau_M = epsilon/sigma, where n_e/n_h are equilibrium mobile-carrier densities,
not automatically donor density or injected numerical parcels. Compare relevant
relaxation modes with carrier motion and readout times. The conducting, dielectric
and intermediate regimes need different justification.
[Riegler (2019)](https://doi.org/10.1016/j.nima.2019.06.056)
([preprint](https://arxiv.org/abs/1812.07570)) treats time-dependent weighting for
finite conductivity and electrode impedances. A planar two-layer analytic test is
a useful next control; assigning its conductivity to AK02 still requires evidence.

## Real measured signals as validation targets

[Aguayo et al., NIM A 701 (2013)](https://doi.org/10.1016/j.nima.2012.11.004)
([preprint](https://arxiv.org/abs/1207.6716)), Fig. 6, compares measured fast
full-energy and slow energy-degraded PPC charge/current pulses. The caption
states 500 ns averaging for current and additional display smoothing. It motivates
rise-time/energy-deficit and current-asymmetry checks, but its numerical timing
and apparatus are not AK02 input parameters. Figure traces are not raw samples.

[Abt et al., SolidStateDetectors.jl](https://arxiv.org/abs/2104.00109), Fig. 7,
compares measured and simulated superpulses; preamplifier response and cross-talk
matter. Treat measured preamp voltage, ideal induced charge, derived current and
ADC samples as distinct data products, with processing and calibration recorded.
[Temperature-dependent drift measurements](https://arxiv.org/abs/2210.04256)
also motivate checking an actual detector's transport parameters rather than
assuming a universal default. The original SAP22 ADL model has no temperature
rescaling; a 77 K override alone does not calibrate its velocities.

No AK02/SAP22 raw measured waveform set has been identified and validated in this
round. Do not fabricate a measured-vs-simulated overlay, digitize smoothed figures
without labeling it, or republish private laboratory data automatically.

## Electronics validation gate

Identify the actual preamp/shaper/ADC and obtain pulser response, noise, sample
interval, polarity, trigger/selection and gain records before fitting hardware.
The front-panel shaping constant need not equal pulse peaking time; for example,
[ORTEC 572A documentation](https://www.ortec-online.com/products/electronic-instruments/amplifiers/572a)
states a factor of 2.2. This is an instrument-specific example, not identification
of the installed laboratory amplifier. Slow collection with finite shaping can
change pulse height without representing the same mechanism as carrier loss.
A single pulser/energy calibration must be independent of each event's truth.

## Experimental source and independent checks

[experiment.json](../transport/experiment.json) records the owner's top-on-Al-lid
Cs137/Am241 arrangement and deliberately unresolved dimensions. It is not runnable
as an as-built model. A decay source needs emission probabilities, coincidences,
atomic relaxation and a per-decay timing/normalization contract. A 662 keV beam
is not an entire Cs137 source. Preserve its existing interface-test identity.

[Radford's icpc_siggen](https://github.com/radforddc/icpc_siggen) is a possible
independent electrostatic/bulk-signal cross-check, not a replacement for calibrated
Li-layer transport. Further implementations should distinguish mathematical
verification, numerical sensitivity, parameter inference and experimental validation.
The next bounded tests are chosen in PROGRESS.md; no reference curve is silently
promoted into an AK02 fit or a universal three-region collection-efficiency table.

The owner's dissertation baseline-equipment table identifies an LBNL Square
preamp (BF862, nominal0.6pF), ORTEC671 shaper, ORTEC927 MCA and Keysight
DSOX3034A scope. This is documentary provenance, not confirmation of a particular
AK02 acquisition. [ORTEC671](https://www.ortec-online.com/products/electronic-instruments/amplifiers/671)
supports Gaussian/triangular analog shaping; [ASPEC927](https://www.ortec-online.com/products/electronic-instruments/multi-channel-analyzers/basic-analog/aspec-927)
uses pulse-height ADCs, not a stored waveform sampling stream. Exact model revision,
filter mode, gains, ADC channel range and pulser response still require run records.
Thus an analog-shaper-to-peak-ADC chain is the documented starting architecture,
not an assumed digitize-first digital-trapezoid chain.
