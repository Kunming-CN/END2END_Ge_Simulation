# End-to-end germanium detector simulation

**[Open the detector results website](https://kunming-cn.github.io/END2END_Ge_Simulation/)** · [GeGI strip explorer](https://kunming-cn.github.io/END2END_Ge_Simulation/detectors/GeGI_3D/strip_explorer.html) · [Development progress](PROGRESS.md)

## Current release

A static library of 17 detector models: geometry/field views, drift movies, pulse comparisons, and signal tables. GeGI includes 20 selectable events, 34 signed channels, and a separate supplementary notebook study. Read the [website guide](https://kunming-cn.github.io/END2END_Ge_Simulation/guide.html) before interpreting the results.

These are precomputed SSD results, **not an online solver or a full end-to-end simulation**. Movies are pre-rendered 3D views; full scene rotation still requires the original desktop ParaView workspace. The original gallery's synthetic deposits are not a Geant4 source simulation or a Compton reconstruction.

To browse a downloaded repository, open `docs/index.html`. No Julia, ParaView, Node.js, or Python installation is needed for viewing. The development computer's full local entry remains `Additional_Simulations/Visualization_3D/Open_Library.cmd`.

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
| `.local/` | Ignored migration backup and bounded test/build scratch space | No |
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
