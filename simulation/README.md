# Configurable SSD CPU / NVIDIA examples

For the nominal LBNL end-to-end workflow, start with the [Windows setup checklist](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html#setup). This document is the advanced standalone SSD reference. The low-code LBNL preflight requires exactly Julia 1.13.0; the standalone parser accepts 1.13.x but other patch versions are not certified by that preflight.

This cache-free example uses the exact distributed YAML snapshots and relative includes. Geometry, bias, impurity, drift and trapping settings remain those of the selected model. Catalog status/assumptions are included in each report. These bounded calculations do not reproduce the website's full numerical campaign or establish convergence or experimental agreement.

Use the reviewed Julia **1.13.0**, SSD **0.11.8**, and the supplied CPU project or optional `gpu/` project (CUDA **6.4.0**). Keep each Project/Manifest pair together. The CPU environment does not require or import CUDA. The GPU environment must already be provisioned with its locked dependencies and a working NVIDIA driver; the runner neither installs packages nor changes the driver. CPU runs are also allowed in the GPU project for fair comparisons. Reports hash the manifest actually selected by Julia.

Install the locked dependencies once from the repository root (internet is needed on first installation):

```console
julia --startup-file=no --project=simulation -e "using Pkg; Pkg.instantiate()"
# Optional NVIDIA environment only:
julia --startup-file=no --project=simulation/gpu -e "using Pkg; Pkg.instantiate()"
```

These commands do not upgrade the lockfiles. No system CUDA toolkit installation is required for this tested setup; CUDA.jl uses its managed artifacts and the existing NVIDIA driver. Then, from the repository root:

```console
julia --startup-file=no --project=simulation simulation/run.jl --help
julia --startup-file=no --project=simulation simulation/run.jl --list-models
julia --startup-file=no --project=simulation simulation/run.jl --check-models
julia --startup-file=no --threads=2 --project=simulation simulation/run.jl
```

The no-argument example remains BEGe_GD32B_reference, one synthetic 662 keV deposit at Cartesian `(12,5,18)` mm, contact 1, 2 ns steps, 20000 maximum drift samples, 0.25 mm minimum refinement spacing and 2 mm initial maximum spacing. It solves both potentials, calculates the CPU electric field, drifts charge and integrates the electrode signal. `--check-models` checks hashes/includes and constructs all 17 models without solving fields or writing a report.

Explicit examples (use a new output directory for each run):

```console
julia --startup-file=no --threads=2 --project=simulation simulation/run.jl --model Bipolar_reference_3D --position-mm 0,0,4.75 --device cpu --energy-kev 662 --contact 1 --dt-ns 2 --max-steps 20000 --threads 2 --min-grid-mm 0.25 --max-grid-mm 2 --output .local/bipolar-cpu
julia --startup-file=no --threads=2 --project=simulation/gpu simulation/run.jl --device cuda --output .local/bege-cuda
```

Every non-default model requires an explicit position. `--contact` defaults to that model's catalog readout ID. Positions are Cartesian millimetres even for cylindrical YAMLs. Outside-semiconductor points and contact-start points are rejected before solving; no automatic movement of an invalid deposit is requested. Inputs must be finite, within the conservative Float32 input range (also enforced for Float64 solves), and positive where appropriate; step count is restricted to 2–1000000, minimum spacing cannot exceed maximum spacing, and requested threads cannot exceed Julia's startup pool. Small positive grid spacings can still be very expensive for large 3D detectors. No all-detector field batch is implied by listing/loading the catalog.

`--threads` limits the requested SOR/field threads, not the Julia process. SSD can choose fewer SOR threads on small grids and uses the full Julia pool in some geometry setup code. Set Julia's startup `--threads=N` too if a process-wide compute-thread ceiling is needed. Reports record both the pool size and requested limit.

CUDA is imported lazily and guarded by `CUDA.functional()`. Failure aborts without CPU fallback. Both electric/weighting potential solves **and their extra iteration checks** receive `CUDA.CuArray`; a latest-world entry handles Julia methods loaded by the optional import. Electric-field construction, charge drift and signal integration remain on CPU. Reports include the backend, GPU memory/name, CUDA package/runtime/driver API versions, NVIDIA driver release from NVML (or an explicit unavailable marker), CPU and thread counts, and separate synchronized solve/field/drift/signal timings. Small grids may be slower on GPU because of setup, compilation and transfer costs.

## Outputs and signal meaning

Default output is `.local/quickstart/`. `--output DIR` must name a **new directory below this project's `.local/`**; relative paths are relative to the current working directory. Existing directories/files and paths resolving outside that tree are refused, including redirects into protected source directories. The original `.local/quickstart/` baseline is not overwritten. A failed solve can leave its reserved directory; inspect it and select a new output for a retry.

| File | Meaning |
|---|---|
| `signal.csv` | Time, signed induced equivalent-energy signal (keV), dimensionless signed charge fraction |
| `waveform.svg` | Plot of the calculated signed fraction |
| `run.json` | Model status/assumptions and hashes, active environment hash, parameters, hardware, iteration checks, endpoints and timings |

`induced_equivalent_energy_keV` is **not reconstructed event energy**. The dimensionless fraction divides SSD's signed signal by the deposited energy; it never divides by the final signal. Existing readout polarity is preserved. Partial/trapped events and step-limit events are retained even when final fraction differs from one. Endpoint records give positions, geometrically intersected contact IDs, sample counts and whether the cap was reached. `stopped_without_contact` is an observation, not a definitive diagnosis of trapping; geometric contact membership alone does not prove full collection.

The baseline is deterministic: diffusion and self-repulsion are disabled, with no random draws/seed needed. The model's charge-trapping configuration is retained through SSD's signal calculation. No recombination model is introduced or claimed. There is no radiation transport, Fano statistics, electronics, noise, ADC or reconstructed energy here. Deposition time is not a drift time.

## Bounded parity/timing benchmark

```console
julia --startup-file=no --threads=2 --project=simulation/gpu simulation/benchmark.jl --output .local/ssd-benchmark
julia --startup-file=no --threads=2 --project=simulation/gpu simulation/benchmark.jl --model Bipolar_reference_3D --position-mm 0,0,4.75 --output .local/bipolar-benchmark
```

The shared runner makes one full warm-up per backend followed by two repetitions per backend, each with a fresh Simulation and identical physical/numerical parameters. GPU work is synchronized at timing boundaries. The default BEGe point, the stated Bipolar point, or GeGI at the centre is accepted; spacing cannot be finer than the default and max steps cannot exceed 20000. This is six solves, not a unit test. The two backend paths share the GPU environment, whose actual manifest hash is recorded.

One `benchmark.json` records hardware, setup time, first-call and repeated stage/wall timings, CPU-time/GPU-time ratios (values above one mean GPU is faster), run endpoints/end charges, and max/RMS differences. First-call timing includes compilation encountered during that run, but is not a cleared disk/kernel-cache measurement; startup/package import is excluded and backend setup is timed separately.

Potential/field comparisons require identical grid ticks, coordinate systems and boundary metadata. Different adaptive grids are reported explicitly, with no elementwise comparison or claim of established parity. Charge fractions are linearly interpolated onto `start:dt:min(end_cpu,end_cuda)` over their shared time support; there is no tail extension or waveform alignment. End charges, durations (within one time step), and endpoint/contact/step-limit statuses are checked separately.

Prospective parity gates are fixed in `benchmark.jl`: max/RMS potential differences of `1e-5/3e-6` scaled by bias (electric) or unity (weighting); field component differences of `1e-3/1e-4` scaled by the CPU peak field magnitude; fraction differences of `1e-3/2e-4`; final-fraction difference at most `1e-4`. Zero-bias electric potential uses its peak absolute value instead. These are numerical parity criteria, not a physical uncertainty budget. Material disagreement, endpoint/duration disagreement or unmatched grids yields a nonzero exit after saving the report. Investigate failures; do not loosen gates to force a pass. No speedup is guaranteed.

For the larger GeGI example (one weighting potential, not all 34 channels):

```console
julia --startup-file=no --threads=2 --project=simulation/gpu simulation/benchmark.jl --model GeGI_3D --position-mm 0,0,0 --min-grid-mm 0.5 --max-iterations 50000 --precision 64 --output .local/gegi-benchmark
```

The GeGI benchmark requires minimum spacing at least 0.5 mm to bound this smoke workload; it is not the full high-resolution GeGI campaign. Parity gates are unchanged.

## Lightweight validation

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_run.jl
julia --startup-file=no --project=simulation simulation/run.jl --check-models
```

Unit tests cover options/help/model choices, invalid numbers, protected outputs and pre-solve geometry checks. They load benchmark syntax but run no field solves and do not import CUDA. Actual CPU regression against the preserved 146-sample baseline and the six-run GPU comparison are separate supervisor checks. Do not change either lockfile or the canonical models to satisfy tests; upgrades require separate review.

## Charge-physics audit: acceleration is not improved physical accuracy

The installed SSD 0.11.8 source was inspected separately from the GPU tests.
Drift models in the distributed originals include anisotropic ADL models and
an inactive-layer mobility model. Preserve the actual model, temperature,
crystal orientation and impurity assumptions; a faster field solve changes none
of those. The current CLI deliberately keeps diffusion/self-repulsion off for
a deterministic CPU/GPU baseline; it does not claim to validate charge clouds.

SSD's diffusion branch depends on the drift model: when a matching scalar
`calculate_mobility` method exists it uses `D = mu*kB*T/q`; otherwise it uses the
material's `De`/`Dh` values. Both use isotropic random steps of length
`sqrt(6*D*dt)`. Do not assume a model-temperature change also recalibrates the
fallback material diffusion constants. For validation, distinguish per-axis
variance `2*D*t` from three-dimensional mean-square displacement `6*D*t`.

The existing Boggs/constant-lifetime trapping models act on the induced-signal
calculation, not by stopping every trapped carrier's precomputed drift path.
The inspected constant-lifetime implementation removes `q*dt/tau` per step,
so `dt << tau` and a time-step study matter. A fitted effective trapping lifetime
is not automatically a validated recombination or detrapping model. No dedicated
SRH/recombination or detrapping solver was identified in this pinned source;
none has been added here. Those mechanisms require a stated model and data.

Next validation work: time/grid/cloud sampling convergence; uniform-field drift
and diffusion checks; analytic trapping limits; and comparison with measured
bulk/surface waveforms. See the [SSD charge-drift documentation](https://juliaphysics.github.io/SolidStateDetectors.jl/stable/man/charge_drift/)
and pinned source `src/ChargeDrift/ChargeDrift.jl`, `src/ChargeTrapping/ChargeTrapping.jl`.

`--max-iterations` controls the potential iteration budget per refinement (250–50000; default 10000). It does not relax the fixed iteration or parity tolerances. The initial GeGI run with 10000 iterations failed its electric-potential gate; that failure was retained instead of reporting a speed result. See PROGRESS.md for the separately tested larger-budget run.

`--precision 32|64` selects the simulation arithmetic; the default remains Float32. Float64 is available for numerical diagnostics without changing YAML parameters or relaxing tolerances. Performance must be measured for that precision. After the extra electric-potential relaxation, the runner restores SSD bulk/depletion/inactive point classifications before computing fields.

## Measured local examples

RTX 4070 Laptop GPU, driver 610.62, Julia 1.13.0 / SSD 0.11.8 / CUDA 6.4.0. CPU was limited to two Julia threads. Warm means over two repeats, excluding startup/first compilation; each solve uses a fresh Simulation:

| Model / precision | CPU 2-thread warm mean (s) | CUDA warm mean (s) | CPU/CUDA ratio |
|---|---:|---:|---:|
| bege / Float32 | 0.377 | 1.412 | 0.27 |
| bipolar / Float32 | 3.335 | 3.818 | 0.87 |
| gegi64 / Float64 | 81.833 | 20.384 | 4.01 |

All three CPU/CUDA parity checks passed. The GeGI Float64 example is about four times faster here; small examples are not. Do not generalize this to every detector, precision, CPU-thread count or all-channel campaign. GeGI Float32 failed the strict iteration check with these coarse-grid settings, so the documented diagnostic command uses Float64 instead of loosening the tolerance. Full evidence and limitations are in ../PROGRESS.md.

## Radiation deposit replay: AK02 and SAP22

First generate the reviewed flat LH5 and `events.json` with [transport/handoff.py](../transport/README.md).
From the repository root, use the existing CPU environment:

```powershell
julia --startup-file=no --threads=2 --project=simulation simulation/replay.jl --input .local/m2a/AK02/events.json --inspect
julia --startup-file=no --threads=2 --project=simulation simulation/replay.jl --input .local/m2a/AK02/events.json --output .local/my-AK02-response --max-events 10 --temperature-k 77
julia --startup-file=no --threads=2 --project=simulation simulation/test_replay.jl .local/m2a/AK02 .local/m2a/SAP22
julia --startup-file=no --threads=2 --project=simulation simulation/test_replay.jl --linearity .local/m2a/AK02
```

The last command adds one actual field solve and a simultaneous multi-deposit
comparison; ordinary tests do not solve fields. `--inspect` verifies all positive
deposits, immutable input hashes, the prepared identity placement and SSD geometry
before any solve. Rotated-transform mathematics is unit-tested, but the runtime
producer is explicitly identity-only. Source/run identity comes from the hashed
raw LH5 plus event ID, not an event number alone across multiple input files.

The default replay retains 78 K from the canonical model. `--temperature-k 77`
updates the in-memory semiconductor and applicable drift temperature without
editing YAMLs or annealing parameters. **SAP22's original ADL temperature model
is Vacuum/no scaling:** its drift-velocity parametrization is unchanged at 77/78 K.
That fact is recorded in `run.json` and checked at a fixed electric field.

Replay selects the first N **primary IDs**, including zero-deposit events, and
keeps all their recorded positive-energy deposits. It subtracts primary time once,
shifts each independent signal causally, and sums on a common grid. No signal is
present before creation; the final cumulative charge is held after its simulated
endpoint. This is valid for the stated noninteracting baseline, not interacting
charge clouds. Diffusion and self-repulsion remain off; zero-field termination is
explicitly on. Do not interpret this as a neutral-layer diffusion study.

Outputs stay together in the new requested `.local/` directory: `signals.csv`,
`run.json`, and one representative `waveform.svg`. Reports include input/code/env
hashes, raw-row identities, original/effective conditions, potential histories,
per-deposit endpoints and signed charge. `stopped_without_contact` and step limits
are retained; near-unit induced charge is not proof of geometrical collection.
The output is keV-equivalent electrode signal, **not ADC reconstructed energy**.
Physical units use the model's stored ionisation energy, also recorded in the report.

This replay uses Float64, a 0.05 mm minimum refinement spacing, explicit SOR=1,
and at most four bounded post-solve relaxation checks per potential. SSD may stop
on an update plateau before reaching its numerical gate. Every returned update is
recorded and the original tolerance remains mandatory; no retry relaxes it. The
shared synthetic runner still defaults to one extra check. These are iteration
gates, not a Poisson residual or grid-convergence study. CPU is the tested replay
backend; the optional CUDA route is not claimed as separately validated for M2a.

Before Li-layer interpretation: diagnose stopping locations, test grid/time/cloud
sampling and neutral-region diffusion, and constrain profile/lifetimes with data.
Before electronics: preserve charge/current polarity, delayed events and flags;
calibrate the actual preamp/shaper/ADC rather than fitting each event to truth energy.

## Collection endpoint diagnostics (not calibrated CCE)

From the repository root, run the CPU-only diagnostic with the existing environment:

```powershell
julia --startup-file=no --threads=2 --project=simulation simulation/test_collection.jl
julia --startup-file=no --threads=2 --project=simulation simulation/diagnose_collection.jl --output .local/my-collection-diagnostics
```

The new output directory contains `depth-scan.csv` and `run.json`. Canonical model and replay files are unchanged. The shared solver gained only
an optional diagnostic observer; it does not alter numerical defaults. Synthetic 1 keV point deposits sample
12 radial depths at mid-height for AK02 and SAP22, with 1/2/4 ns time steps and
0.05/0.025 mm minimum refinement settings. These are not uniform grid spacings.
Fields are recalculated at 77 K; the original +500/+700 V biases are retained.
The diagnostic alone permits up to eight existing post-solve continuation checks,
records every value, and keeps the original tolerance. Replay defaults are unchanged.

For each start/end point it records E, weighting potential, nearest-grid flags,
Li/net impurity densities, contact distance, and geometric/step-limit status. A step cap is not a guarantee
that the requested elapsed horizon was reached; actual end times are recorded.
It recomputes a no-trapping signal on the **same drift paths** and checks its
endpoint weighting-potential difference. This separates signal induction from
physical arrival at a metal contact; it does not calibrate trapping or recombination.

The separate synthetic zero-field test uses 2048 carriers per species over 400 ns.
With zero-field termination on they do not diffuse; with it off, the material
De/Dh fallback is checked against per-axis variance 2Dt and six-standard-error
statistical gates. A clearance-plus-maximum-excursion bound, full-hop checks and
an elapsed-time check exclude boundary projection or early stopping in this test.
This does **not** test AK02's mobility-dependent near-surface
coefficient, boundary losses, self-repulsion or a physical charge cloud distribution.

**Current interpretation gate:** AK02 near-surface results are strongly grid
sensitive in this no-diffusion setup. In the measured test, the largest change
in signed induced fraction between the two refinement settings was about 0.996.
A fine-grid electron path can also reach the step cap in an extremely small but
nonzero interpolated field. Do not erase that flag or threshold the field to zero
just to obtain collection. Neither a step in the scan nor an iteration-tolerance
pass determines a physical dead-layer thickness or establishes convergence.

SAP22 was much less sensitive for these selected points, but differs in geometry,
impurities and drift model; it is not a one-variable Li-contact control. Further
work must resolve grid/field sensitivity and validate mobility-tied diffusion,
finite observation time and material parameters before quantitative CCE claims.
Method references and the measured evidence are in `../PROGRESS.md`.

The largest observed change is localized at the sampled 0.5 mm radial depth near
the sharp transition in this no-diffusion setup. It is not a measured layer
thickness or evidence that all bulk events/the event interface are incorrect.
Density keys ending in `_cm3` denote number densities in cm^-3, not volumes.

The diffusion ensemble consists of weighted numerical sample points, not a claim
that a 1 keV deposit produces 2048 physical electron-hole pairs. Its acceptance
test concerns positional moments only; self-repulsion is disabled.

## Transition-grid and mobility-branch verification

The [physics/reference map](PHYSICS.md) separates transport assumptions, real
measured pulse benchmarks and prerequisites for calibrated near-surface response.
`validate_transition.jl` has two independent diagnostic phases:

```powershell
julia --startup-file=no --threads=2 --project=simulation simulation/test_transition.jl
julia --startup-file=no --threads=2 --project=simulation simulation/validate_transition.jl --phase fields --output .local/my-transition-fields
julia --startup-file=no --threads=2 --project=simulation simulation/validate_transition.jl --phase mobility --output .local/my-mobility-check
```

The fields phase records actual electric/weighting r-z ticks, profiles on common
2-micrometre depth samples, the doping-compensation root, and reporting-threshold
crossings. It compares minimum-spacing controls and genuinely smaller maximum
cell-spacing caps. Values below a reporting threshold are never clipped. The
fixed-endpoint cross-weighting matrix is a hybrid numerical diagnostic, not a
new physical detector. Signed signals and trajectory-cap flags remain present.
A failed finer solve exits with failure and preserves continuation histories;
passing an update gate alone does not prove grid convergence.

This finer-grid diagnostic explicitly allows up to 64 bounded continuation calls
per potential with the same tolerances. The shared runner default remains one,
M2a replay four, and the earlier collection diagnostic eight. Budget changes are
not automatically applied to ordinary runs or interpreted as physical validation.

The mobility phase uses the actual InactiveLayerChargeDriftModel with spatially
constant, disposable impurity coefficients sampled from three AK02 depths. It
runs 2048 numerical parcels per species for 400 ns at 1/2/4 ns steps, with exact
zero-field termination disabled. Both species must satisfy Einstein-hop, full
duration, boundary-clearance, mean, variance and cross-covariance guards. The
statistical screens are six-standard-error bounds; they do not establish a
sub-percent calibration. The original field and detector are restored afterward.

These homogeneous tests do not choose a variable-D transport closure or validate
boundary recombination. Original lifetimes, impurity inputs, the material
ionisation energy and locked dependencies are not changed. The fields phase
writes `profiles.csv` and `run.json`; mobility writes its compact `run.json`.
Source hashes and exceptions are retained. Use new output directories instead of
overwriting the original experiments. See PROGRESS.md for completed and failed
cases, not just whether the program produced a file.

The regular `fields` phase includes five cases through the 0.05 mm maximum-tick
cap. The more expensive 0.025 mm stress case is separate:

```powershell
julia --startup-file=no --threads=2 --project=simulation simulation/validate_transition.jl --phase fine --output .local/my-fine-stress
julia --startup-file=no --threads=2 --project=simulation simulation/validate_transition.jl --phase mobility --output .local/my-mobility-8192 --parcels 8192
```

**Known unresolved result:** the finer 0.025 mm stress attempt failed the unchanged
electric update gate after its bounded 64 continuations. It remains a failed
case, not a removed data point. Even the passing 0.1/0.05 mm maximum-tick cases
show a moving threshold crossing, so physical CCE/dead-layer interpretation remains
blocked. Two-micrometre profile sampling is not two-micrometre field resolution;
reported brackets are first sampled exceedances, and a missing lower endpoint is
censored. The extra `--parcels` option only changes homogeneous sample statistics,
not the fixed 1/2/4 ns time-step matrix or any detector coefficient.

## Independent analytic electrostatic verification

This is an independent finite-volume diagnostic, not an alternative production
SSD solver. It solves a charge-free cylindrical annulus with fixed inner/outer
voltages and compares with the analytical logarithmic potential and radial field.
No AK02 geometry, depletion algorithm, carrier model or package is modified.

From the repository root:

```powershell
julia --startup-file=no --project=simulation simulation/test_electrostatics.jl
julia --startup-file=no --project=simulation simulation/verify_electrostatics.jl --output .local/analytic-check
```

The output must be a new directory. It contains only `profiles.csv` and `run.json`.
Three nested nonuniform grids (17/33/65 nodes) are checked against predeclared
boundary, normalized residual, conservative flux, analytic error and refinement
rate gates. The report retains the actual grids, values and source checksum.
Tests also cover constant/reversed bias, log-spaced nodal accuracy and deliberate
perturbations. Constant-bias field errors have explicit absolute V/m units.

Passing verifies this independent operator and its checks only. A subsequent
comparison must apply an independent residual/flux diagnostic to SSD's own output;
this result does not resolve the AK02 fine-grid depletion failure or validate CCE.

## Direct analytic verification of SSD electrostatics

`verify_ssd_electrostatics.jl` solves the pinned SSD infinite-coaxial example on
three explicit nonuniform grids. This is a synthetic homogeneous, source-free
CPU test, not an AK02 depletion or Li-layer calibration. The electrical faces
are **5.1 and 34.9 mm**, at 0 and 10 V; the finite-thickness contact geometry is
kept unchanged. The analytic solution is logarithmic in radius.

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_ssd_electrostatics.jl
julia --startup-file=no --threads=2 --project=simulation simulation/verify_ssd_electrostatics.jl --output .local/ssd-electrostatics-new
```

The second command requires a new output directory and saves `profiles.csv` and
`run.json`. It runs 17/33/65 annular-node cases plus zero, equal, reversed and
offset-bias controls. Reports retain actual ticks, masks, charge-source arrays,
source/manifest hashes, native vector fields, continuation checks, failed gates
and independent finite-volume diagnostics. No production solver is modified.

The finest tested errors were 9.56e-6 of the voltage span and 1.60e-4 relative
interior radial-field error, with approximately second-order refinement.
**Contact-interface field errors remain separate: about 1.61% and 1.11% on that
grid.** They must not be hidden behind the smaller interior result. The native
coefficient equivalence to the reference FV operator has not been demonstrated;
its residual on SSD output is labeled a consistency diagnostic, not proof of
production algebraic/depletion accuracy. See `PROGRESS.md` for exact evidence.

## Synthetic preamp, analog shaping and peak ADC

`readout.jl` consumes the signed cumulative charge CSV and report from `replay.jl`.
It does not solve detector fields or fit event truth. The frozen engineering
configuration is `readout_demo.json`: 0.6 pF feedback capacitance, 50 us feedback
and matched pole-zero time constants, a 0.5 us RC pole, gain 20, and a 14-bit
0..10 V peak ADC. These assumptions are not a calibrated ORTEC 671/927 model.

Current is reconstructed from original charge-bin differences. Exact state-space
propagation produces a negative CSA pulse and positive compensated CR-(RC)^2
output for supported positive charge. A separate 500 keV-equivalent delta-charge
injection fixes volts/keV; every event uses that calibration. The recorded SSD
pair energy, presently 2.95 eV, controls charge conversion. No per-event Edep
normalization, added resolution smearing or inferred collection correction is used.

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_readout.jl
julia --startup-file=no --threads=2 --project=simulation simulation/readout.jl --input .local/RUN/AK02/charge --truth .local/RUN/AK02/transport/events.json --config simulation/readout_demo.json --output .local/RUN/AK02/readout
```

The frozen standalone demo configuration expects all 100 primary records.
The pipeline driver may generate a separately hashed per-run configuration that
changes only `expected_primary_count`; all selected primaries are still required.
It never edits the frozen source configuration or retunes electronics parameters. Rejected pulses retain
IDs and flags but have null reconstructed energy; readout acceptance does not
clear incomplete SSD trajectories. Any negative cumulative charge is explicitly
outside this conservative unipolar example's accepted waveform domain, including
tiny excursions; signed values are never rectified or silently repaired.

Readout sampling/window verification against a completed pipeline is available:

```console
julia --startup-file=no --threads=2 --project=simulation simulation/verify_readout.jl --input .local/my-example --output .local/readout-check-new
```

It compares all saved pulses with 1/4 ns electronics grids and a doubled
observation tail, retaining the original injection slope. This tests fixed-input
readout discretization, not SSD drift-step convergence. ADC-code changes are
reported rather than forbidden: a tiny analog change can cross a code boundary.

## Native lithium-region diagnostics (not a calibrated production response)

`diagnose_lithium.jl` replays the preserved 200-event AK02/SAP22 source, retaining
original endpoint flags and checking same-path NoTrapping against the Ramo
endpoint identity. It then compares independent native diffusive parcels with
the no-diffusion baseline across the AK02 radial transition. Each seed/depth
uses 32 numerical parcels totaling 1 keV; these are not a measured carrier cloud.

```console
julia --startup-file=no --threads=4 --project=simulation simulation/test_lithium.jl
julia --startup-file=no --threads=4 --project=simulation simulation/diagnose_lithium.jl --input .local/m3b/release --output .local/li-diagnostic-new --phase all
```

The input must be the completed schema-2 source with the recorded 2 ns, 77 K,
Float64 and baseline field settings; arbitrary configurations fail instead of
being silently reinterpreted. `audit` and `depth` select bounded subsets. Output
is one report plus endpoint, depth and field-profile CSVs under the chosen root.
No detector YAML, SSD package or original waveform is changed.

`small_conditional_remainder` uses the noncancelling sum
`abs(1-W_h)+abs(W_e) <= 1e-4`. It describes a static, no-further-loss completion
assumption, not geometrical collection, recoverable pulse height or validated
CCE. Native variable-D diffusion, finite conductivity, surface physics and
transition-grid convergence remain separate accuracy questions. All unresolved
stops, time caps and sensitivity outcomes remain recorded.

## Transition-grid and native fixed-point audit

`diagnose_transition_grid.jl` is a separate deterministic AK02 diagnostic. It
reproduces the two historical field solutions, verifies that weighting calculations
do not overwrite the electric/depletion state, and checks both native red/black
update groups before testing explicit nested grids. It does not change the
production solver or recompute the public carrier signals.

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_transition_grid.jl
julia --startup-file=no --threads=2 --project=simulation simulation/diagnose_transition_grid.jl --output .local/grid-check-new --phase all
```

The output has `report.json`, `profiles.csv` and `smallcomparisons.csv`. A partial
or budget-failed diagnostic is retained explicitly; process completion is not
convergence. The checks use the pinned native operator, not an independent proof
of its continuum PDE. Contact checks concern grid nodes within the contacts, not
arbitrary interpolated surface points. Source sums include fixed/contact cells.

The optional report command adds those outcomes without replacing earlier Li data:

```console
python tools/lithium_report.py --input .local/m2c/results --grid-input .local/grid-check-new --output .local/li-grid-view-new
```

Two additional CSVs accompany the standalone HTML/summary. Partial cases remain
labelled, the previous signal/grid warning is retained, and exporter checks reject
mismatched source hashes or false convergence metadata.

## Same-grid initialization and crossed-axis attribution

`diagnose_transition_axes.jl` reuses the pinned native-grid helper without changing
production code. It reproduces the two historical field states, initializes two
independent solutions on the same finest grid, and evaluates the four crossed
radial/axial grids from one common parent. All new cases are E-only after baseline
hash verification; this is not a charge/weighting-potential or CCE calculation.

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_transition_axes.jl
julia --startup-file=no --threads=2 --project=simulation simulation/diagnose_transition_axes.jl --output .local/axes-new
```

The single output root contains report.json and two full-precision CSV files.
Native acceptance and same-grid agreement are separate: seven accepted native
solutions may still fail the strict whole-domain voltage agreement criterion.
Crossed effects then remain explicitly conditional diagnostics. All four effects
use the same pointwise E22 normalization; zero-field onset remains descriptive,
while the 1 V/cm threshold has its predeclared conservative comparison bound.

Fresh states have a 40,000-sweep limit; continuation has 20,000. The 900-second
case budget is cooperative at native-call/checkpoint boundaries and includes
postprocessing, not a hard wall-time guarantee. Contact checks concern nonempty
sets of contact-member grid nodes, not arbitrary between-node boundary accuracy.
Initial coefficient/mask/alpha identity, independent storage and parent hashes
are checked; potential is the only intentionally changed initialization field.

## Use native Li transport through the existing readout

The selected-event example is a delivery feature, not another field-solver study:

```console
julia --startup-file=no --threads=2 --project=simulation simulation/native_li_example.jl --input .local/m3b/release/AK02/transport/events.json --output .local/native-li-new
```

Open `comparison.html` in the output directory. One field solve is reused for
legacy and native responses. The native branch enables SSD diffusion and disables
zero-field termination, then causally sums equal-energy independent parcels before
calling the unchanged preamp/shaper/ADC functions with one injection calibration.
Events 0,2,41,78 retain their original IDs and rows; the other source events are
explicitly unprocessed. Only events 41/78 receive the extra seed/count comparisons.
The input is the checked prior transport output, not a new radioactive source.

The report, scalar CSV and full signed charge CSV preserve negative inputs,
trajectory limits and readout rejection. The frozen readout conservatively rejects
any negative cumulative charge; this can reject native stochastic traces even
when an analog peak exists. Do not rectify charge or change seeds to obtain an
accepted event. Parcel variation and the known transition-grid discrepancy remain
uncertainties; this small selected sample is not a calibrated spectrum.

The frozen legacy replay remains unchanged for reproducibility. Its default
`diffusion=false`/zero-field-stop behavior is not the native RCC demonstration.
Run `simulation/test_native_li_example.jl` for the bounded interface tests.

An explicit peak-policy selection retains signed stochastic excursions while
allowing a valid positive shaped peak through the same electronics:

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_peak_policy.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_readout.jl
julia --startup-file=no --threads=2 --project=simulation simulation/native_li_example.jl --input .local/m3b/release/AK02/transport/events.json --output .local/native-li-signed-new --peak-policy signed_input_positive_peak
```

Omitting the option preserves `legacy_reject_negative_input` and the frozen demo
electronics. The standalone readout JSON may explicitly include `peak_policy`,
`peak_gate_start_ns` and `peak_gate_end_ns`; both gate bounds must be finite and
supplied together, relative to primary creation. The sampled peak is searched
inside the inclusive gate. A positive peak at either gate boundary is rejected
as incomplete; a zero or negative peak stays below threshold. Activity outside
the gate is recorded independently, without removing deposits or resetting time.
The independent injection calibration is unchanged by gate selection.

`negative_input`, `below_threshold`, `saturated`, `gate_limited`,
`window_limited`, and out-of-gate activity remain separate diagnostics, even when
the scalar rejection reason reports only the first applicable reason. Analog
voltage outside ADC range is recorded over the full numerical waveform;
digitization uses only the gated peak. Transport endpoint flags remain separate
from electronic acceptance. No sign rectification or event-wise gain fit occurs.

With three completed matching native fixtures, run
`julia --startup-file=no --threads=2 --project=simulation simulation/test_native_peak_regression.jl BASELINE_DIR LEGACY_DIR SIGNED_DIR`.
This read-only regression checks full charge CSV identity, all case identities,
transport/analog invariants and exact policy outcomes. Deliberate identity and
acceptance mutations must fail. It performs no additional field solve. Peak-gate
activity diagnostics compare original current-bin intervals with requested bounds,
including bins that only partly lie outside a fractional-time gate.

## Reusable native response and versioned electronics profiles

`native_response.jl` reuses the selected example's native SSD helper and the
existing Float64 field solver for AK02 (+500 V) or SAP22 (+700 V), explicitly at
77 K. There is one shared field solution per model/run. Diffusion is on,
zero-field termination and self-repulsion are off, and independent equal-energy
parcels retain the 2 ns grid and nominal 10 us trajectory cap. Default16 and
optional32 parcels describe numerical sampling, not physical resolution.
The original selected14-case CLI and frozen schema1 readout remain separate.

Inspect and test first in the existing pinned environment; these tests do not
solve fields or launch radiation transport. Use one or two Julia threads only.

```console
julia --startup-file=no --threads=2 --project=simulation simulation/test_readout_profiles.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_native_stream.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_native_response.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_readout.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_peak_policy.jl
julia --startup-file=no --threads=2 --project=simulation simulation/test_native_li_example.jl
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/m3b/release/AK02/transport/events.json --inspect
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/m3b/release/SAP22/transport/events.json --inspect
```

Run the two100-primary comparisons serially, each into a fresh output root:

```console
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/m3b/release/AK02/transport/events.json --output .local/native-response-AK02-100
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/m3b/release/SAP22/transport/events.json --output .local/native-response-SAP22-100
```

`--profile simulation/native_readout_profile.json` selects the additive schema2
contract (the default). Copy this small profile into `.local/` to choose finite,
positive feedback capacitance/decay, shaping pole/gain/PZ, ADC full scale and
threshold,2..24 ADC bits, peak policy and paired gate bounds. Every setting must
be explicit; unknown keys fail. A resolved config can differ from the profile
only in expected primary count, checked independently of hashes. Schema2 bounds
samples per group and streams the campaign; it does not inherit the legacy
whole-run sample cap. Do not edit `readout_demo.json` or a canonical model.

The profile is synthetic electronics, not a measured hardware model. One separate
ideal injection calibration is shared by all groups, without truth-dependent gain.
Analog preamp and shaping outputs precede a single digital peak ADC code. The
analog numerical grid and bounded display traces are not waveform digitization.
Gate bounds are relative to the primary for mono-gamma input, or to the local
group origin for Cs137; peak acceptance never removes a decay from the census.

For an already completed Cs137 stream (replace the illustrative transport path):

```console
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/cs137-AK02-20/stream/manifest.json --inspect
julia --startup-file=no --threads=2 --project=simulation simulation/native_response.jl --input .local/cs137-AK02-20/stream/manifest.json --output .local/native-response-AK02-20 --charge-csv examples --trace-examples 4
```

This entry consumes transport only; it never generates a campaign. Cs137 requires
`cs137_decay_stream_v1`, completed manifests, unchanged raw LH5/prepared/run/config/
geometry/macro/source hashes, contiguous global decay IDs, raw row census,
ancestry, transforms and exact half-open pulse assignments. It does not apply
the mono-gamma primary validator or energy ceiling to an ion decay. The source
manifest and prepared metadata are copied into the response root. Source hashes
must still match the producer files at inspection and completion.

Cs137 retains the producer's nominal isolated-window convention: every positive
Ge row is assigned once, zero rows remain in truth, and electronics reset at
each group. The numerical readout ends strictly before the horizon; original
absolute times, local origins, group identity, boundary/recovery/tail flags and
untruncated native endpoints survive. Long-lived daughter timing never allocates
a minutes-long waveform. A grouping window is not a recovery/pileup model.
Material energy is recorded-only, with escape/neutrino/full closure null.

Outputs are streamed `truth.jsonl`/`truth.csv`, `scalars.jsonl`/`scalars.csv` and
`endpoints.jsonl`/`endpoints.csv`. Every decay has a scalar row, including zero-hit
decays with no fabricated pulse. Every accepted/rejected/saturated group has a
pulse row. The quoted `record_json` CSV column preserves **all** readout diagnostics,
current balance and transport flags, including simultaneous rejection conditions.
Endpoint rows retain the original raw row and every parcel/carrier flag and seed.
Seeds depend on original event/global decay ID, raw row and parcel index, never
chunk position or a newly selected pulse ID.

`signals.csv` contains all signed native charge samples for the <=100-primary
mono-gamma demonstration (zero-charge primaries have no group ID). For streams,
the default saves only the first four group traces. `--charge-csv all|examples|none`
and `--trace-examples 0..16` are explicit storage choices; they never sample the
scalar/endpoint census. `traces.jsonl` contains bounded display samples.
`summary.html` is an offline additive summary with selected expandable traces;
it exports only completed hash-checked files and uses no external framework.
`histograms.json`/CSV distinguish per-initial-decay, per-emitted660..663keV-photon
and per-accepted-pulse denominators. Stage bins are5keV with explicit under/overflow;
they do not alter stored scalar precision or imply physical FWHM. Mono-gamma
decay and decay-photon normalization are null; per-primary normalization is
separate. Timing separates field solves, native response
and electronics from startup/preflight; output sizes and process peak RSS are
recorded when available, without capacity extrapolation.

Supervisor checks now include the native/profile/stream suites, both 100-primary
mono-gamma comparisons, prepared Cs137 stream preflight and a positive 500-decay
full-pipeline pilot for each detector. These are engineering integration checks,
not calibrated Li response or physical resolution. See `../PROGRESS.md` for the
current verified campaign state and `../tools/NATIVE_CAMPAIGN.md` for the guarded
500-to-10k entry and post-run offline comparison.

### Explicit isolation of native numerical failures

The general entry accepts `--native-failure-policy abort|record`, default `abort`.
The campaign launcher explicitly chooses `record`. Only `ArgumentError` with
exact messages `Noncontact endpoint outside crystal` or `Invalid waveform support`
inside the native helper call can become a recorded failure; other exceptions and
readout checks still abort. The original helper and its geometry/waveform guards
are unchanged. No physical transport correction is implied.

Failed groups keep their truth, IDs, raw rows, delays, seeds/settings and exact
error in `native-failures.jsonl`. Unavailable response fields are null. The strict
helper does not expose rejected endpoint details; that absence is explicit, not
a claim that endpoint values were preserved. No failed-group signal or endpoint
is fabricated. `native_failed_groups` and `readout_rejected` are separate counts,
and a run with any failed groups has status `completed_with_native_failures`.
Native/analog histograms exclude unavailable values rather than filling zeros;
truth histograms and initial-decay denominators remain complete.
