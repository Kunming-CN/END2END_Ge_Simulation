# End-to-end germanium detector simulation

**[Open the detector results website](https://kunming-cn.github.io/END2END_Ge_Simulation/)** · [GeGI strip explorer](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/GeGI_3D/strip_explorer.html) · [Development progress](PROGRESS.md)

**[Native lithium-region diagnostics](https://kunming-cn.github.io/END2END_Ge_Simulation/lithium/lithium.html)** — endpoint accounting, diffusion depth response, native residual/state checks and explicit nested-grid sensitivity; not calibrated Li collection efficiency.

**[Native SSD lithium response through electronics](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/native-li/comparison.html)** — four selected original events, legacy/native modes, fixed seeds and parcel counts, shared injection calibration, all rejection and cap flags visible. This is a provisional engineering demonstration, not a calibrated spectrum.

## Current release

**[Completed 1M/model Geant4 to native SSD and peak-ADC comparison](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-1m-response/report.html)**: 23,693 positive-deposit groups, 21,672 accepted responses, 1,613 electronics rejects and 408 unavailable native responses. The initial-decay denominator remains one million per detector; results are engineering simulations, not calibrated experimental predictions.

**[Interactive AK02 geometry](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/AK02/geometry.html)** and **[SAP22 geometry](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/SAP22/geometry.html)** reuse saved ParaView surface meshes. Rotate, zoom and toggle contacts; field/trajectory interaction is not claimed by these geometry-only viewers.

### Earlier compact example

**[Open the completed 1M-per-detector Cs137 response](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-1m-response/report.html)**: saved Geant4 deposition truth → native SSD charge response → synthetic shaping and peak ADC for AK02 and SAP22, with native/input-domain failures and electronics rejects accounted separately. This is an engineering response study, not calibrated CCE, a physical FWHM measurement, or agreement with an experimental spectrum.

**[Explore the compact radiation-to-readout example](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/pipeline.html)**: 100 primary photons each for AK02 and SAP22, with every event preserved through Geant4/remage, SSD, preamp, analog shaping and peak ADC. This is a verified engineering workflow, not a calibrated detector/cryostat prediction.

Also available: a static library of 17 detector models: geometry/field views, drift movies, pulse comparisons, and signal tables. GeGI includes 20 selectable events, 34 signed channels, and a separate supplementary notebook study. Read the [website guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) before interpreting the results.

The website serves precomputed results, **not an online solver**. The end-to-end examples close the engineering radiation-to-readout chain; advanced Li physics, real apparatus metrology and hardware calibration remain unresolved. Featured AK02/SAP22 detector geometry is now rotatable directly in the browser; the larger saved field/drift gallery remains pre-rendered, with desktop ParaView still useful for full scientific scene inspection. The original gallery's synthetic deposits are not a Geant4 source simulation or a Compton reconstruction.

To browse the saved static galleries in a downloaded repository, open `docs/index.html`. Their images and embedded reports need no runtime installation. The new geometry viewer fetches scene JSON: use GitHub Pages, or serve `docs/` over local HTTP (for example, `python -m http.server 8765 --bind 127.0.0.1 --directory docs`) rather than opening its HTML via a `file://` URL. The development computer's full local entry remains `Additional_Simulations/Visualization_3D/Open_Library.cmd`.

## Run the reviewed LBNL Cs137 scenario without writing code

On Windows, double-click `Run.cmd`. The menu provides **Check setup / New run / Resume / Open results / Status**. The first reviewed scenario is the nominal LBNL cryostat with an uncollimated Cs137 source and AK02, SAP22, or both detectors. It reuses the pinned Geant4/remage, SSD and synthetic-electronics implementations; the launcher does not introduce another solver.

The presets are intentionally bounded: **smoke = 20 initial decays per selected detector** (installation check; it may produce no Ge pulse), **demo = 500** (default first end-to-end run), and **larger = 10,000** (requires a verified clean 500-event pilot). Million-decay production remains an advanced workflow, not a beginner default.

```console
Run.cmd check
Run.cmd run -Preset demo -Detector both
Run.cmd status
Run.cmd resume -Name RUN_NAME
Run.cmd open -Name RUN_NAME
```

Scientific settings live in [`scenarios/lbnl-cs137.json`](scenarios/lbnl-cs137.json), which references the canonical geometry and readout profile rather than duplicating them. Machine-specific paths and executable commands are not stored in the scenario file. Each run is created under `.local/runs/<name>` with immutable scientific receipts, hashes, logs, and a local `index.html` linking the saved response summaries.

Resume is conservative: hash-verified completed prepare/transport/stream/native stages are reused; an incomplete transport/stream/native attempt is preserved and stops for inspection rather than being silently deleted and rerun. This v1 does **not** advertise group-level continuation inside an interrupted small native-response stage. The separately validated checkpoint workflow remains the path for long native production runs.

The pinned LBNL text-geometry originals are **not redistributed** because no explicit license was found in the pinned upstream tree. `Run.cmd check/setup` verifies the exact expected files under `.local/transport/LBNL`; see [`transport/cryostat-source.json`](transport/cryostat-source.json) for the upstream commit, inventory and hashes. Setup does not silently substitute geometry or install unreviewed physics packages.

## Run the complete engineering example

First prepare the pinned [Julia CPU environment](simulation/README.md) and
[Geant4/remage environment](transport/README.md). The driver needs Python 3.10+
standard library only; it installs nothing.
On this development computer the existing ParaView Python can run the same script.
For example, replace `python` with `& "$env:ProgramFiles/ParaView 6.1.1/bin/pvpython.exe" --no-mpi --disable-registry` in PowerShell.

```console
python tools/pipeline_demo.py run --output .local/my-example --events 100
python tools/pipeline_demo.py export --input .local/my-example --output .local/my-example-view
```

Open `.local/my-example-view/pipeline.html` directly; all data is embedded, so
rendering works offline. The companion `data.json` exposes the same records.
The initial view selects the first nonzero deposit; navigation also offers zero
and highest-deposition examples without filtering the event census or histograms.

The default run processes both AK02 and SAP22 at explicit 77 K and canonical
biases. `--model AK02` selects one model. Choose `--preset quick` (10 photons
per model at 662 keV), `--preset gamma-662` (default: 100 at 662 keV), or
`--preset gamma-59` (100 at 59.5 keV). These are monoenergetic engineering
scenarios, not complete isotope decays or exact reference line energies.

`--events 1..500`, `--energy-kev` (positive and at most 10,000 keV), and
`--seed` explicitly override the preset. The energy cap bounds workload; it is
not certification of physical accuracy over that whole range.
`--threads 1` is the low-load option; the default is 2, with at most 4 allowed.
Detector jobs and stages remain serial. Child-only BLAS/OMP environment settings
avoid nested thread pools; no systemwide environment or user applications change.
The generated root `readout-config.json` changes only the expected event count;
feedback, shaping, gain, ADC and calibration settings remain frozen and checked.
Existing outputs are never overwritten. `JULIA_EXECUTABLE` overrides discovery.

```console
python tools/pipeline_demo.py run --preset quick --threads 1 --output .local/quick-test
python tools/pipeline_demo.py run --preset gamma-59 --events 20 --threads 1 --output .local/low-energy-test
```

One output root contains `run.json` plus each model's `transport/`, `charge/`
and `readout/` stages. Manifests bind source/data hashes, commands, identity,
calibration and failures. Export validates those completed artifacts without
rerunning physics. A clean source-only checkout was tested on the same Windows
computer without the original field caches; other hardware/OS validation is pending.

## Run a small calculation on your computer

The [shared SSD runner](simulation/README.md) loads a selected distributed model and calculates fields, charge drift and one electrode signal from scratch. Its default CPU example uses the BEGe reference, with optional NVIDIA acceleration available through a separate environment. It requires Julia 1.13.x and the supplied lockfile, but no GPU, private field cache, ParaView or Geant4. It is a bounded example, not a reproduction of every website simulation.

## One project root

| Path | Purpose | In this repository? |
|---|---|---|
| `Additional_Simulations/` | Existing models, calculation code, original numerical data and full desktop library | Not yet; portability is M1 |
| `2D_GeGI detector Simulation/` | Earlier GeGI study and source reference material | No |
| `docs/` | Generated, validated public website | Yes |
| `models/` | 17 exact original SSD YAML snapshots, shared include and portable provenance | Yes |
| `simulation/` | Shared CPU/CUDA runner, causal event replay, pinned environments and tests | Yes |
| `transport/` | Pinned Geant4/remage, bare-detector geometry, event adapter and tests | Yes |
| `tools/` | Export, publication checks, tests and maintenance utilities | Yes |
| `.local/` | Protected raw campaigns/checkpoints plus local test/build evidence; not blanket-disposable | No |
| `PROGRESS.md`, `AGENTS.md` | Milestones, evidence, and development rules | Yes |

Only `docs/` is served by GitHub Pages. Raw caches, native scenes, manuals, photographs, slides, and private machine paths are excluded. The source calculation folders are deliberately preserved rather than reorganized during the publication milestone.

The intentional [model distribution](models/README.md) preserves original YAML bytes and hashes, including candidate/scenario/reference labels and assumptions. These are SSD geometry and semiconductor configurations, not CAD/STL files or field caches. Nine models share one packaged drift-velocity include. Packaging is not numerical convergence or experimental validation.

## Updating results on the development computer

Change the scientific source or its presentation generator, then test it and update `PROGRESS.md`. Do not edit generated files in `docs/` by hand. Double-click `Publish.cmd` to rebuild, validate, commit the approved publication files and push to `main`; GitHub Pages publishes `main:/docs`. No force-push is used.

The exporter first builds in `.local/site-build`, checks links, privacy, file sizes and SHA-256 inventory, then replaces `docs/`. Unchanged snapshots are not rewritten. A failed validation leaves the previous published folder intact. Generated staging/previous folders are cleaned; Windows read-only attributes are handled only within those generated folders. ACLs are not changed.

A failed network push leaves the local commit available for retry. Do not force-push to solve conflicts. The helper's basic reachability check is not an exact-version check: run the independent verification below after deployment.

## Checks that work from a clean repository clone

Python 3.10+ and its standard library are sufficient for these checks. Live HTTPS verification needs SSL support; when the bundled ParaView Python lacks it, the checker reuses installed Node.js without disabling certificate verification. No simulation data outside the repository is needed:

```sh
python tools/test_site.py
python tools/export_models.py --validate
python tools/check_site.py
python tools/check_site.py --url https://kunming-cn.github.io/END2END_Ge_Simulation/
```

The live check compares the exact snapshot manifest, every HTML page, every model/download artifact, and representative image, video and data files. A not-yet-deployed version fails rather than being reported as current. The manifest contains per-file hashes and a deterministic build ID; Git is configured to preserve the exact website and model YAML bytes across operating systems.

Building new exports is different: `tools/build_site.py` requires the original local results and GeGI source notebook. The publication helper currently uses the installed Git, GitHub CLI, Node.js and ParaView Python on the development computer; `SITE_PYTHON` overrides its Python executable. Full-campaign calculation/build portability remains a separate milestone; the small CPU quickstart has its own environment and instructions.

Model downloads build only from versioned `models/`: direct YAMLs, per-detector ZIPs with includes and metadata, and one all-model ZIP. Detector pages, the homepage and the guide provide their download links. Explicit `python tools/export_models.py --import` reads the original catalog and approved source roots, checks pinned hashes, and refuses differing managed outputs; it is not part of normal publication. Never edit scientific originals to satisfy an import check.

## Maintenance boundaries

`tools/site_guide.html` is the editable web-guide template. The existing library generators remain the authority for galleries and scientific displays. `tools/check_site.py` and `tools/test_site.py` guard the public deliverable. `tools/migrate_paths.py`, `tools/smoke_scene.py` and `tools/smoke_test.jl` serve the original workspace and are not standalone simulation entry points.

For subsequent substantial development, use one focused branch, record the purpose and tests, then review before merging to `main`. Keep model changes separate from presentation changes. Never silently alter original model parameters or discard incomplete-collection events. The staged development plan and Astra/High preference are in `PROGRESS.md` and `AGENTS.md`.

## AK02 / SAP22 radiation-to-charge example

The [transport instructions](transport/README.md) now generate a bare AK02 or SAP22
Geant4 geometry from the exact SSD contour, run a bounded monoenergetic photon
source and export a checked event contract. The [SSD replay](simulation/README.md#radiation-deposit-replay-ak02-and-sap22)
then computes electrode signals with the original deposition times and energy
ledger. Zero-deposit primaries and incomplete-trajectory flags are retained.

AK02/ICPC2 is the Li-contact primary case; SAP22 is a differently shaped non-Li
cross-check, not a matched control. Canonical 78 K and +500/+700 V files remain
unchanged; 77 K is an explicit run override. SAP22's original ADL parametrization
has no temperature scaling. These are interface tests, not Li-layer CCE or
electronics validation. LBNL cryostat conversion/placement and calibrated charge
response remain separate gates; no new GeGI work is included.

The [collection diagnostic](simulation/README.md#collection-endpoint-diagnostics-not-calibrated-cce) now separates endpoint status from induced charge and tests a zero-field diffusion limit. It exposes strong AK02 near-surface grid sensitivity; quantitative CCE/dead-layer interpretation remains blocked. These synthetic scans do not replace the original gallery or radiation-event results.

## Physics references and experimental configuration

The [physics/reference map](simulation/PHYSICS.md) connects implemented models to
primary papers, measured-pulse examples and explicit validation limits. The
[transition verification](simulation/README.md#transition-grid-and-mobility-branch-verification)
checks actual grid nodes/field profiles and the real inactive-layer diffusion
branch in controlled homogeneous limits. A failed fine-grid stress case is
retained; homogeneous diffusion agreement is not calibrated surface collection.

[transport/experiment.json](transport/experiment.json) records the owner's
Cs137/Am241 source placement on the aluminum lid above the detector, separates
baseline equipment documentation from run-specific settings, and leaves unknown
geometry/source/calibration fields explicit. It is deliberately not a runnable
as-built setup. Do not replace unknown dimensions with another detector's geometry.

## Independent checks and spectra-only validation

The [analytic electrostatic verifier](simulation/README.md#independent-analytic-electrostatic-verification)
checks a source-free annulus against an exact solution; it does not certify the
production depletion solver. The [EM spectrum comparison](transport/README.md#em-constructor-spectrum-sensitivity)
compares Livermore/Penelope/Option4 at deposited-energy level with independent-seed
controls and explicit uncertainty. Neither replaces semiconductor charge transport.

The owner confirmed that original AK02/SAP22 pulse waveforms were not saved;
measured energy spectra remain available. Experimental validation therefore
targets spectrum observables with run/background/calibration metadata and explicit
parameter degeneracies, not recovery or fitting of nonexistent waveforms.

## Maintain the two-contact geometry illustrations

The geometry key uses **contact 1 = orange-red**, **contact 2 = cyan-blue** and
translucent grey-blue bulk. IDs, names and voltages come from the canonical
model catalog; colors do not infer doping type, Li diffusion thickness or charge
collection. Existing GeGI channel displays, field views and signal movies retain
their own schemes. Small contacts retain their actual scale.

Use the existing ParaView 6.1.1 Python on the development computer:

```powershell
$pv = 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe'
& $pv --no-mpi --disable-registry tools/render_contacts.py --all --output .local/contact-review-new
# Inspect the staged PNGs before applying them.
& $pv --no-mpi --disable-registry tools/render_contacts.py --apply .local/contact-review-new
.\Publish.cmd
```

The renderer reuses the original meshes and cameras; it does not solve fields.
Apply checks original/staged hashes, stores one `originals.zip` and receipt, and
replaces only the 16 geometry PNG/PVSM pairs. Caught failures are rolled back;
a host crash or failed rollback still requires inspecting the saved originals.
Do not reuse an applied/failed stage or delete its evidence before inspection.

The local `.local/contact-display-applied.json` index prevents publishing a
new color key alongside stale images after an old gallery rebuild. Generated
`docs/` remains read-only-by-convention: edit the generator, stage, inspect,
apply, test and publish instead. The portable site validator does not require
this private index. For an intentional palette change, stage all 16 with the reviewed new style, then
apply with `--upgrade-style`. The prior ledger and native hashes are checked and
backed up; do not delete them to bypass a mismatch. Changes to numerical source
metadata or original meshes are not palette upgrades and require their own
reviewed provenance update. Current stages include renderer/exporter/test
hashes; changing those files after staging requires restaging.

## Final goal and two development lanes

The goal is a local, reproducible radiation-to-readout simulation that another
student can run and inspect—not merely a large collection of plots, and not an
online calculation service. The critical path is the smallest complete chain:
Geant4/remage deposits -> SSD electrode charge -> preamp -> analog shaping ->
peak-height ADC -> reconstructed energies and a small diagnostic spectrum.

Advanced Li-region/finite-conductivity validation, detailed cryostat/source
metrology, response calibration and experimental comparison form the accuracy
lane. They remain required before quantitative physical claims, but do not block
a clearly labeled engineering prototype. The existing AK02/SAP22 conditions,
original models and prior diagnostics stay traceable; GeGI development is deferred.

A complete example must preserve event identity, zero-deposit records, incomplete
charge flags, units, calibration and file hashes across every stage. Its browser
view must show those same records, not just a selection of attractive waveforms.
See PROGRESS.md for current completion and unresolved gates rather than treating
successful execution or a matching plot as experimental validation.

## Lightweight runs and lossless viewing

The `quick` preset reduces event/output scale, not fixed environment startup or
field-solve overhead. On this computer its total startup-dominated runtime was
close to the 100-event default; do not expect speed to scale with event count.
Use `--threads 1` when keeping the computer responsive matters more than maximum
throughput. No user applications, global thread settings or power plans change.

Public schema-2 bundles use compact JSON without rounding numbers or dropping
records. Original raw reports remain readable. Large event/provenance details
are formatted only when their panels open, and refresh with the selection.
The current default still contains all 200 events and their charge flags.

Archived schema-1 runs/bundles remain preserved and usable with their original
release. The new driver rejects mixing incompatible manifests rather than
rewriting historical provenance. Generate a new named output for schema 2.
The independent sampling verifier supports both the old default and validated
per-run census configurations; `simulation/test_verify_readout.jl` tests that
compatibility without running detector physics.

## Saved native Cs137 campaign: 10,000 initial decays per detector

[Open the 10k comparison, stage spectra, traces and complete response ledgers](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-10k/comparison.html).
[Run and publication commands](tools/NATIVE_CAMPAIGN.md).

This is the nominal LBNL cryostat → real Cs137 decay → native SSD response →
preamp → analog shaping → peak-ADC engineering workflow, not a calibrated
experimental prediction. All 20,000 initial decays remain represented.
AK02: 121 pulse groups = 107 accepted + 13 electronics rejects + 1 native failure.
SAP22: 115 = 113 accepted + 1 electronics reject + 1 native failure.
The formal status is `completed_with_native_failures`; failed response values
remain unknown. AK02 has 119 step-limited groups among 120 successful native
groups; ADC acceptance never clears transport flags or proves complete collection.
Public ZIPs retain every original response ledger byte. Raw LH5 and upstream
geometry stay in the local campaign. No larger run or global Li convergence
claim is implied by these saved results.

### Actual Geant4 geometry and saved radiation events

[Open the 3D geometry and all-event viewer](https://kunming-cn.github.io/END2END_Ge_Simulation/examples/cs137-10k-geometry/geometry.html).
Both 10,000-primary datasets retain every saved material step and track-creation
record, including zero-Ge events. Download the exact GDML, run macro and setup
receipts from the viewer. STEP chords do not reconstruct missing world-air paths,
and are not SSD carrier trajectories or all-event electronics waveforms.

The nominal source is centered above the curved cylindrical aluminum wall,
not a surveyed flat axial lid; source-to-crystal distances are about 26 mm.
See [the placement and low-deposition audit](tools/SOURCE_GEOMETRY.md) and
[geometry/export reproduction instructions](tools/geant4_scene/README.md).
