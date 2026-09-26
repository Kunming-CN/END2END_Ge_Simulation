# Configurable SSD CPU / NVIDIA examples

This cache-free example uses the exact distributed YAML snapshots and relative includes. Geometry, bias, impurity, drift and trapping settings remain those of the selected model. Catalog status/assumptions are included in each report. These bounded calculations do not reproduce the website's full numerical campaign or establish convergence or experimental agreement.

Use Julia **1.13.x**, SSD **0.11.8**, and the supplied CPU project or optional `gpu/` project (CUDA **6.4.0**). Keep each Project/Manifest pair together. The CPU environment does not require or import CUDA. The GPU environment must already be provisioned with its locked dependencies and a working NVIDIA driver; the runner neither installs packages nor changes the driver. CPU runs are also allowed in the GPU project for fair comparisons. Reports hash the manifest actually selected by Julia.

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
