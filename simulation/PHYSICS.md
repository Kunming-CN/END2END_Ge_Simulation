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

The owner confirmed on 2026-09-26 that original AK02/SAP22 measured waveforms
were not saved; only energy-spectrum data remain. Do not search indefinitely for
nonexistent pulse files or reconstruct unique pulses from spectra. Literature
traces remain method illustrations, never substituted AK02/SAP22 measurements.
Spectrum comparison must retain channel/energy calibration, counts, background,
live time, bias and shaping settings. Peak positions/widths/areas, tails and
continuum windows can constrain an effective spectral response, but do not
uniquely identify mobility, diffusion, trapping, recombination and shaping losses.
Report nuisance-parameter degeneracy and use withheld features where possible.

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

The canonical neutral-impurity value `5.6769e15 cm^-3` also appears in the
[upstream SSD TrueCoaxial inactive-layer tutorial](https://juliaphysics.github.io/SolidStateDetectors.jl/stable/tutorials/dead_layer_simulation/).
That establishes a matching reference setting, not its experimental provenance
for AK02. Retain it for reproducibility, but do not describe it as a measured
neutral concentration without a separate record. Likewise, effective lifetimes
and annealing-based Li profiles require detector-specific inference/validation;
passing a diffusion-code check does not establish those inputs.

The same tutorial constructs an explicit nonuniform grid with locally finer
ticks near the Li region. After independent analytic residual verification,
this existing grid API is a candidate for targeted refinement instead of further
uniform whole-domain tightening. Actual ticks, depletion mapping, boundary
residuals and failed gates must still be recorded; tutorial success on a simple
coaxial example does not certify AK02.

## Geant4 models: radiation physics versus charge response

The owner's recollection of different Geant4 spectrum models has a useful basis.
[remage physics-list documentation](https://remage.readthedocs.io/en/stable/manual/physicslist.html)
and pinned `RMGPhysics.cc` map Livermore, Penelope and Option4 to Geant4 EM
constructors. They select radiation interaction/secondary-particle models:
photoelectric absorption, Compton/Rayleigh scattering, ionisation, bremsstrahlung
and charged-particle transport. They do not replace SSD's band-carrier mobility,
diffusion, trapping or semiconductor boundary conditions. Option4 is a mixed
choice of process models, not simply a 'fourth-order correction'.

[Atomic relaxation](https://geant4.web.cern.ch/documentation/dev/prm_html/PhysicsReferenceManual/electromagnetic/atomic_relaxation/relaxation.html)
redistributes vacancy energy among fluorescence photons, Auger electrons and
local deposition. Escape can change spectral structure. Record actual fluorescence,
Auger, PIXE and deexcitation-cut settings rather than guessing from a constructor.
Production cuts control secondary creation treatment; they are not track step
limits. Step limits matter for spatial deposits near a later-applied Li response
boundary, even when total energy per Geant4 volume is already stable.

[Soti et al. (2013)](https://arxiv.org/abs/1306.4538) compare Geant4 electron
process/multiple-scattering choices against HPGe/Si beta-detector measurements.
This supports a model-sensitivity study, but historical versions and beta geometry
cannot rank our Geant4 11.3.2 gamma-source configurations. Preserve the Livermore
baseline; choose any change through validation, not because it fits one feature.

Other corrections are distinct: remage supports radiative beta-decay inner
bremsstrahlung and custom neutron-capture gamma cascades, which modify the source
emission/interaction physics, not drift. The present monoenergetic gamma exercise
does not test those processes or full Cs137/Am241 branching and coincidences.
User applications may also apply charge-collection or resolution corrections
*after* Geant4; keep such response layers explicitly identified.
[G4CMP](https://www.pnnl.gov/publications/g4cmp-condensed-matter-physics-simulation-using-geant4-toolkit)
is a separate condensed-matter extension including cryogenic carrier/phonon
transport, not functionality enabled by switching Livermore to Penelope. It is
not installed or validated for this project's 77 K Li-contact problem.

`transport/compare_em.py` compares rounded 59.5/662 keV monoenergetic photons in the
same bare AK02 side-on geometry, retaining zero-deposit primaries, raw step truth,
actual model banners, data-package versions and atomic settings. It is not the
owner's on-lid geometry, an isotope source, measured peak shape or efficiency.
Unbroadened 0.5 keV histograms and deposited-energy containment are diagnostic.
Each energy has one independent-seed Livermore control. Marginal Wilson intervals
and independent Newcombe-Wilson difference intervals are exploratory, not
simultaneous confidence bands, equivalence tests or accuracy rankings.

The final run's 59.5 keV same-Livermore repeat differs enough that its unadjusted 95%
difference interval excludes zero; this is explicitly retained. Multiple
exploratory comparisons and finite Monte Carlo counts prohibit selecting a
constructor from these fluctuations. Additional preplanned independent seeds
and statistical controls would be required before asserting a model effect.

The independent-binomial interval follows Newcombe, Statistics in Medicine17
(1998),873-890, doi:10.1002/(SICI)1097-0258(19980430)17:8<873::AID-SIM779>3.0.CO;2-I.
The additional Fisher/Holm analysis is explicitly post-hoc: six containment
contrasts, including same-constructor controls. It is reported alongside, not in
place of, the original marginal intervals. No significance-based seed selection
or model substitution is permitted. SciPy used for exact tests is already pinned
in the transport environment; no dependency version was changed.

## Flow-first readout prototype (M3a; synthetic, not a hardware fit)

The minimum chain is radiation deposits -> signed cumulative electrode charge ->
current -> finite-feedback charge-sensitive preamp -> compensated analog shaping
-> peak-height ADC -> independently calibrated reconstructed energy. This
engineering prototype may run before production Li/finite-conductivity validation;
those unresolved uncertainties remain visible, not silently calibrated away.

The [ORTEC 671](https://www.ortec-online.com/products/electronic-instruments/amplifiers/671)
and [ASPEC-927](https://www.ortec-online.com/products/electronic-instruments/multi-channel-analyzers/basic-analog/aspec-927)
manufacturer descriptions support analog shaping followed by pulse-height
conversion. The 671's actual Gaussian/triangular network is not claimed to equal
our ideal CR-(RC)^2 transfer. A front-panel shaping setting is not automatically
our RC pole constant or pulse peaking time. A published
[charge-amplifier/CR-RC/pole-zero implementation](https://indico.cern.ch/event/299180/contributions/1659568/)
provides architectural context, not AK02 calibration constants.

For the chosen sign convention the CSA has transfer
`H_CSA(s) = -1/[Cf*(s + 1/tau_f)]`. The downstream compensated stage is
`H_shape(s) = -G*tau_s*(s + 1/tau_pz)/(1 + s*tau_s)^3`.
With `tau_pz=tau_f`, a positive impulse Q produces
`V_shape(t) = G*Q/(2*Cf)*(t/tau_s)^2*exp(-t/tau_s)` for t>=0.
It peaks at `2*tau_s`; that definition fixes gain normalization independently
of detector truth. Exact matrix-exponential propagation handles constant-current
bins; sampled peak accuracy must still be checked against time-step refinement.

## Planned adjustable electronics and large-source comparison

The owner requested 10,000 or 100,000 events per detector only after Li handling
is sufficiently understood. The agreed first target is 10,000 initial Cs137 decays
per detector, after a 500-decay timing/memory/record-size pilot and the gates in
`transport/experiment.json`. A larger count is a measured capacity/statistics
decision, not an automatic cap or an efficiency claim.

Keep parent-decay, emitted-photon and accepted-pulse normalizations separate.
The [remage generator documentation](https://remage.readthedocs.io/en/stable/manual/generators.html)
explains ion sources, decay chains and initial-decay time resetting. Resetting the
parent time does not make delayed daughter emissions prompt. The new adapter must
retain daughter/track/row identities and split finite electronics windows without
dropping late deposits or summing minute-scale decay chains into one charge pulse.
A real source capsule is not the Am241 capsule found in the upstream LBNL example.

The next readout extension will use named, versioned profiles separate from the
frozen demonstration. Changes must pass independent charge-injection/impulse tests,
then reuse the same detector event set for parameter comparisons. Do not tune each
event to its deposited truth or confuse an analog RC pole with a manufacturer's
front-panel shaping setting.

| Profile stage | First adjustable controls | Required independent check |
|---|---|---|
| Charge-sensitive preamp | Feedback capacitance, feedback decay, fixed polarity, finite bandwidth as a later option | Delta-charge gain/decay and withheld-amplitude linearity |
| Synthetic analog shaping | RC pole time, fixed CR-(RC)^2 initially, gain, matched or explicitly mismatched pole-zero time | Analytic impulse/rectangle response, peaking time, slow-charge ballistic deficit |
| Peak ADC | Channel count/bit depth, full-scale voltage, threshold, finite peak gate, clipping policy | Transition codes, half-LSB error, negative/overrange/threshold census |
| Rate response, subsequent phase | Baseline restoration, pileup rejection, conversion dead time | Double-pulse separation and known-rate time stream; no rate claim without activity/live time |

The [ORTEC 671](https://www.ortec-online.com/products/electronic-instruments/amplifiers/671)
provides 0.5/1/2/3/6/10 us settings, GAUSS/TRI choices, gain/polarity, baseline
restoration and pileup functions. Those are manufacturer controls, not proof that
our ideal RC cascade reproduces its exact transfer function. The
[ASPEC-927](https://www.ortec-online.com/products/electronic-instruments/multi-channel-analyzers/basic-analog/aspec-927)
provides selectable 512..16384 channels and gate/PUR/busy behavior. A synthetic
configurable ADC may expose broader ranges, but must not be labeled an exact 927.

A separate waveform-digitizer branch may later reuse
[LEGEND dspeed](https://dspeed.readthedocs.io/en/stable/) rather than reinventing
trapezoid, cusp/ZAC, pole-zero and baseline processors. These digital processors
act on sampled waveforms and are not substitutes for the present analog-shaper
then peak-ADC ordering. Their additional parameters require a recorded sampling
rate, quantization, noise model and distinct calibration tests.

A high-statistics spectrum must not confuse numerical parcel sampling with real
carrier fluctuations. The present 32 weighted parcels per seed estimate a native
mean response; their finite Monte Carlo spread is not detector energy resolution.
Before production, quantify that numerical error against the desired spectral
precision, or use a validated precomputed mean-response/kernel with interpolation
checks. Physical pair statistics, trapping fluctuations and electronics noise
must be modeled separately without double counting. Simply drawing 32 weighted
trajectories for every deposited site could add artificial spectral broadening.
This is an additional campaign gate, not a reason to discard the diagnostic curves.
