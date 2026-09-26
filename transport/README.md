# Geant4/remage: radiation transport, not semiconductor charge transport

This directory keeps one pinned Linux environment for radiation energy deposits.
Windows uses Ubuntu 24.04 under WSL2; SSD remains native Windows Julia.
The Pixi manifest pins remage 1.1.0 and Geant4 11.3.2, selected from the same
conda-forge build family. Keep pixi.toml and pixi.lock together; upgrade on a
branch and rerun the smoke test before merging. Do not use a floating latest image.

## Boundaries

Geant4/remage models radiation interactions and records deposited energy,
position, time and event identity. SSD models electron/hole drift and electrode
signals. Electronics, digitization and reconstructed energy are a later layer.
Installing remage does not improve or validate carrier diffusion, trapping or
recombination. These must be checked against the selected SSD model and data.

## The laboratory cryostat

The user selected jintonic/geant4 at commit
`1ff3371e0afb804115773af0541b3e56bd660f8c`, directory
`detector/Ge/cryostat/LBNL`. See cryostat-source.json for original file hashes.
The original files are retained locally in `.local/transport/LBNL/`; they are
not substituted with a generic cryostat and are not part of the website.
The pinned repository did not expose an explicit license file. This project
records provenance without republishing or relicensing those upstream files.

## Run on the configured Windows computer

From the repository root in PowerShell:

```powershell
.\transport\Run.cmd versions
.\transport\Run.cmd smoke
.\transport\Run.cmd python check_smoke.py
```

`smoke` refuses to overwrite `.local/transport/smoke.lh5`. The supplied Ge box,
100 photons and source macro are installation checks ONLY, not cryostat geometry
or a prediction of experimental efficiency. LH5 output includes metres for
positions, ns for times and keV for energy: conversion to SSD must be explicit.
No-deposit primaries remain represented by the total/vertex data; do not confuse
step rows, deposited events and simulated primaries when building efficiencies.

## Reproduce the Linux environment

Install WSL2/Ubuntu on Windows, then install Pixi inside Linux following its
[official instructions](https://pixi.prefix.dev/latest/installation/).
Native Linux users do not need WSL. Run from `transport/`:

```sh
pixi install --locked
bash run.sh versions
bash run.sh smoke
bash run.sh python check_smoke.py
```

The project-local `.pixi/config.toml` places the large Linux environment in Pixi's
managed Linux cache, not the synced Windows folder. It is a runtime installation,
not a second source checkout. Installation requires several GB for Geant4 data
and dependencies. `Run.cmd` selects Ubuntu-24.04; `run.sh` is the native Linux
entry. Only Linux x86-64 is locked here; macOS is not claimed as tested.

## Before connecting the cryostat to SSD

The upstream is Geant4 `.tg` text geometry, while remage normally reads GDML.
Its `/geometry/source` macro belongs to the original application, not remage.
There are two distinct variants: a monolithic `LBNLcryostat.tg`, and the modular
`planar4wings.tg -> stage.tg -> shield.tg -> chamber.tg` include chain.
Do not merge both variants or silently replace their detector with an SSD model.
The modular detector uses a 10 x 5 x 10 mm bulk and separate handling wings;
its coordinates/orientation must be reconciled with the selected SSD geometry.

Conversion and LBNL overlap/material/placement verification are still pending.
Preserve the distinction between bulk and wings, choose the correct as-built
variant and source placement, then export Geant4 deposit identities/positions/
times without mistaking them for carrier drift times. Preserve zero-deposit
primaries for efficiency and event accounting. Do not cluster deposits before
checking the spatial/time resolution needed by the semiconductor response.

References: [remage installation](https://remage.readthedocs.io/en/stable/manual/install.html),
[remage geometry](https://remage.readthedocs.io/en/stable/manual/geometry.html),
[original LBNL geometry](https://github.com/jintonic/geant4/tree/1ff3371e0afb804115773af0541b3e56bd660f8c/detector/Ge/cryostat/LBNL).

Geometry compatibility warning: the pinned LBNL source sets an end-cap inner
diameter of 67.7 mm, while the distributed GeGI model has a 90 mm body width.
These are not interchangeable hardware setups. Do not automatically place GeGI
inside this cryostat. Start the LBNL coupling with a suitably sized laboratory
prototype and verify the holder/shield clearance and the actual mounting
orientation. Dimensions in these source models are not a substitute for an
as-built survey of the experimental assembly.

## M2a bare-detector event handoff

`handoff.py` prepares immutable inputs, runs remage, and extracts a small JSON
fixture from **flat** LH5. It accepts only canonical `AK02` (Anupama ICPC2,
Li-contact primary case) and `SAP22` (non-Li cross-check with different geometry).
GeGI is deferred. This adapter does not calculate charge or apply charge-loss corrections.
Continue with [the SSD replay](../simulation/README.md#radiation-deposit-replay-ak02-and-sap22).
The example has no electronics, efficiency prediction or experimental validation.

Canonical YAML files, includes and locks are read only. Both the embedded model
SHA-256 and catalog SHA-256 entry must match. SAP22's recorded include is also
checked. The stored 78 K and +500/+700 V baselines are recorded without overrides.
Transport uses NIST `G4_Ge`; temperature, impurity and Li-dependent charge response
remain SSD inputs, not extra Geant4 energy losses.

The entire semiconductor contour becomes sensitive Ge, including the Li region.
Only the semiconductor mass is included. Zero-thickness outer electrodes are
explicitly omitted, as is the separately described finite point-contact overlay;
it is an SSD boundary/contact object, not a second overlapping Ge mass volume.
No cryostat, support, source holder, encapsulation or measured source placement
is invented. The GDML contains a 200 mm vacuum world and an explicit identity
placement. The closed r-z contour is emitted as `genericPolycone/rzpoint` in
original order. Only the duplicate final closing point is omitted because GDML
closes implicitly. Ordinary z-plane `polycone`, CSG, slanted edges, extra
transforms, other materials and other units are rejected.

The synthetic source is one monoenergetic gamma per event, at outer radius +
10 mm on +x and mid-z, aimed along -x toward the detector centre. The default
662 keV is an interface example, not experimental Cs/Am source activity or
geometry. EM uses Livermore, hadronic and optical physics are disabled. Production
range cuts for gamma/e-/e+ are 0.1 mm in the default region and 0.01 mm in the
sensitive region. These are initial smoke-test settings, **not step limits or a
convergence result**. Proton cuts remain remage defaults. All Germanium output
commands follow `/run/initialize`: float64 energies/positions, track and parent
IDs, both endpoints, preclustering off, and zero-energy rows retained. No energy
cuts or row selection are configured. Vertex census and primary-particle output
are enabled. An unsupported macro must fail; nothing retries with fewer fields.

### Run the small example

Use the installed locked environment, with no package installation. In a WSL
terminal, start in the project's `transport/` directory. Windows users can run
the same arguments through `transport\Run.cmd` (which sets that working directory).
Use new output names if any command was attempted previously:

```sh
bash run.sh python -B test_handoff.py
bash run.sh python -B handoff.py prepare --model AK02 --output ../.local/m2a/ak02 --events 100 --seed 260925 --energy-kev 662
bash run.sh python -B handoff.py prepare --model SAP22 --output ../.local/m2a/sap22 --events 100 --seed 260925 --energy-kev 662

bash run.sh cmake -S . -B ../.local/m2a/probe-build -G Ninja
bash run.sh cmake --build ../.local/m2a/probe-build
bash run.sh ../.local/m2a/probe-build/geometry_probe ../.local/m2a/ak02/geometry.gdml ../.local/m2a/ak02/probe-points.txt ../.local/m2a/ak02-probe.json
bash run.sh ../.local/m2a/probe-build/geometry_probe ../.local/m2a/sap22/geometry.gdml ../.local/m2a/sap22/probe-points.txt ../.local/m2a/sap22-probe.json

# After inspecting and comparing geometry-probe results:
bash run.sh python -B handoff.py run --directory ../.local/m2a/ak02
bash run.sh python -B handoff.py extract --directory ../.local/m2a/ak02
bash run.sh python -B handoff.py run --directory ../.local/m2a/sap22
bash run.sh python -B handoff.py extract --directory ../.local/m2a/sap22
```

`prepare` refuses every existing output directory and paths outside this
project's `.local/`, including symlink/junction escapes. Keep generated outputs
under `.local/m2a`. It produces `geometry.gdml`, `run.mac`, `probe-points.txt` and
`prepared.json`. Metadata records canonical model/catalog/lock/manifest/adapter
hashes, GDML/macro/probe hashes, seed, primary count, energy, transform, original
conditions, omissions, analytic volumes and deterministic probe expectations.

`run` requires exactly those untouched prepared files. Save the probe result
**beside** the prepared folder, as above, so the folder is still fresh. It invokes
the following argument array with that folder as `cwd` (no shell construction):

```text
remage --flat-output -t 1 --rand-seed SEED -o truth.lh5 -g geometry.gdml -- run.mac
```

`run.log`, `run.json` and `truth.lh5` remain as evidence, including on failure.
Actual Python/package/remage/Geant4 versions are recorded at runtime, not inferred
from the lock. Successful process exit alone is insufficient: the macro log and
flat data/census/bounds checks must pass. Never retry in the same folder or edit
prepared inputs; prepare a fresh folder after a code or lock change. Preparation
does not launch transport. The default count is 100; no large run was performed
while implementing this handoff.

### Geometry validation

`geometry_probe.cc` is an original, small utility using `G4GDMLParser` and the
named `germanium` logical solid from the generated GDML. It reads plain local
`x y z` millimetre rows, calls the actual solid's `GetCubicVolume()` and `Inside()`,
and publishes a new JSON result with the Geant4 version number and surface
tolerance. It does not recreate the polygon or return expected labels. It has
no particle run and does not test material physics. CMake requires Geant4's GDML
component; all build files belong under `.local/m2a`.

`prepared.json` provides independent cylinder-subtraction reference volumes:

- AK02: pi * (12.65^2 * 9.4 - 7.8^2 * 2.1 - (7.75^2 - 2.95^2) * 1.5) mm^3.
- SAP22: pi * (12.75^2 * 10 - 8.85^2 * 4.2 - (8.75^2 - 3.85^2) * 3) mm^3.

It also stores the polygon first-moment volume. Compare **actual Geant4 and SSD**
against these references and against the same named sample positions before
coupling. For Geant4 11.3.2 this solid provides an analytic volume; a relative
comparison tolerance of 1e-10 is appropriate for these fixtures. Compare probe
indices and coordinates, not just the number of passing points. The samples
cover bulk, axis, lower bore/recess, upper annular groove, exterior, each physical
edge midpoint, and offsets of +/-1e-5 mm. Exact edge points have `surface` labels;
handle SSD's boundary convention separately from strictly inside/outside points.
The r=0 contour seam is not a physical surface. No real rotated Geant4 run is
claimed: nontrivial rotation/translation checks currently use synthetic fixtures.
The probe result itself is evidence, not an automatically completed acceptance
gate; the supervisor must compare and record the G4/SSD results.

### JSON interchange v1

`extract` creates `events.json` only after validating the entire file. It requires
a successful `run.json` and unchanged raw LH5 and prepared-input hashes. Output
is serialized into an exclusive `.partial` sibling, then published with an
atomic no-clobber hard link. Unsupported filesystems fail visibly; no fallback
overwrites existing data. Failure can leave `.partial` evidence but never a
valid-looking truncated final JSON. This is an in-memory format for small
fixtures, not a replacement for the raw LH5 archive.

| Location | Fields / meaning |
|---|---|
| Top level | `schema_version: 1`, `model_id`, `model_sha256`, `source_lh5_sha256`, `geometry_sha256`, `macro_sha256`, `primary_count`, `events` |
| Units | `units: {energy: keV, length: mm, time: ns}`; `global_position_m` is explicitly metres |
| Transform | `coordinate_transform: {rotation_local_to_global: 3x3, translation_global_mm: 3, definition: "x_global_mm=R*x_local_mm+t"}` |
| Event | Integer `event_id`, vertex `primary_time_ns`, `steps`; every generated event appears, even with `steps: []` |
| Step identity | Globally unique integer `raw_row_index` (zero-based physical row of `stp/germanium`), `track_id`, `parent_track_id`, `particle_pdg` |
| Step truth | Finite nonnegative `energy_keV`, unmodified `time_ns`, local `position_mm`, raw `global_position_m`, local `pre_position_mm`, local `post_position_mm` |
| Additional evidence | `energy_sum_keV`, `boundary`, `source_fields`, and `provenance` (runtime versions, lock/run/prepared hashes, seed, energy, scope, omissions) |

The supported LH5 tables are `/stp/germanium` and `/vtx`, with the scalar
`/number_of_simulated_events`. Required step columns are `evtid`, `particle`,
`trackid`, `parent_trackid`, `edep`, `time`, `xloc/yloc/zloc` and their `_pre`/`_post`
variants. Required vertex columns are `evtid`, `n_part`, `time`, `xloc/yloc/zloc`.
IDs require integer storage; energy/time/position require float64 and exact
`keV`/`ns`/`m` attributes. One vertex and one primary per event, event IDs
0..primary_count-1, are deliberate restrictions of this generated source. Other
vertex multiplicities, foreign IDs, bad lengths, missing census, invalid rigid
transforms, nonfinite data, negative energy, or duplicate output rows fail.
Events sort by event ID; each event retains source row order, even when times
are delayed or rows from different events are interleaved.

Despite the name, remage's `xloc/yloc/zloc` are **global** coordinates. Conversion
is explicitly `x_local_mm = R.T * (1000*x_global_m - t)`. Both endpoints undergo
the same conversion. `position_mm` retains remage's representative point (post
point for gamma; average for other particles in Both mode). Nothing substitutes
or nudges radiation positions. Bounds checks cover the representative point and
both endpoints. Anything outside by more than 1e-6 mm is rejected. Points within
that tolerance are marked `surface` in `boundary.surface_rows`, with their
original values retained for a later SSD boundary-policy decision.

`time_ns` is remage's original global step time within its event time reference,
not a carrier drift time or an artificial absolute acquisition clock. Vertex
time is saved separately and is **never added** to it. Reshaped output (including
any `t0` or jagged columns) is explicitly rejected. `t0` is already the first hit
time, not an extra offset. The adapter neither splits nor clusters delayed steps.
It preserves zero-energy rows and zero-hit primaries, checks the exact `fsum`
before/after conversion, and never normalizes energy or subtracts Li-region loss.

`source_fields` inventories step and vertex columns and points to `truth.lh5`.
All unmapped columns (including surface distances), their units/attributes,
global endpoints, primary-particle kinematics and auxiliary tables remain in
that **unchanged hashed raw file**. The JSON does not claim all Geant4 history was
saved: only the output requested by the macro exists. Keep raw LH5, prepared
inputs and runtime evidence together with the JSON.

### Validation and interpretation

The supervising session ran the locked-environment Python tests, built the C++
probe, simulated 100 photons for each detector, validated the raw LH5 and replayed
bounded event sets in SSD. See [PROGRESS.md](../PROGRESS.md) for exact counts,
source hashes, independent review findings and limits. Synthetic tests include
malformed units/IDs, delayed and empty events, path guards, failed publication,
primary photon kinematics, and energy conservation. The tests never need private
manuscripts. Run `bash run.sh python -B test_handoff.py` after changes.

Extraction also checks `/particles`: one PDG-22 photon per primary event, vertex
zero, float64 kinetic energy and momentum in MeV, consistent photon momentum
magnitude, and energy matching the prepared monoenergetic source. Each event's
deposited energy must not exceed that incident energy. These checks verify source
consistency, not measured source intensity or detector efficiency.

The six handoff/replay source files are deliberately allowlisted for Git. Raw
LH5, generated GDML, logs, probe builds and waveforms remain under `.local/`;
never force-add that directory. A code/lock upgrade requires fresh prepared
transport inputs; old raw truth remains readable by the documented schema.

Implementation references: pinned remage 1.1.0
[Germanium output](https://github.com/legend-exp/remage/blob/v1.1.0/src/RMGGermaniumOutputScheme.cc),
[vertex output](https://github.com/legend-exp/remage/blob/v1.1.0/src/RMGVertexOutputScheme.cc),
[position semantics](https://github.com/legend-exp/remage/blob/v1.1.0/src/RMGOutputTools.cc),
[physics commands](https://github.com/legend-exp/remage/blob/v1.1.0/src/RMGPhysics.cc),
and Geant4 11.3.2
[generic polycone](https://github.com/Geant4/geant4/blob/v11.3.2/source/geometry/solids/specific/src/G4GenericPolycone.cc).

## Owner-specified top-source experiment

`experiment.json` records Cs137/Am241 resting on the external aluminum lid above
the crystal, as confirmed by the owner. It also identifies documented baseline
equipment separately from unverified per-run settings. The source active layer,
encapsulation, lid thickness, crystal gap and local-to-lab pose remain explicit
unknowns. Do not reinterpret laboratory above as SSD +z or reuse the old planar
crystal dimensions as an AK02 survey. The configuration is intentionally not
runnable; the side-on monoenergetic M2a tests retain their original identity.

## EM-constructor spectrum sensitivity

Geant4 Livermore, Penelope and Option4 affect radiation interactions and deposits,
not semiconductor drift. `compare_em.py` reuses the checked bare AK02 geometry
and flat LH5 producer, with optional constructor selection in `handoff.py`.
Livermore is still the default. The original default macro is preserved; every
new prepared directory records its selected constructor and diagnostic logging.

From a Windows PowerShell at the repository root:

```powershell
.\transport\Run.cmd python -B test_compare_em.py
.\transport\Run.cmd python -B compare_em.py --output ../.local/em-check --events 5000
```

This executes eight cases: two rounded monoenergetic photon energies (59.5 and
662 keV), three EM constructors and one independent-seed Livermore repeat per
energy. These are bare side-on interface tests, not the owner's lid-mounted
isotopic sources. Source origin, direction, time, primary census and energy are
checked from raw data. Model banners, cuts, atomic-deexcitation settings and
Geant4/data-package versions are retained. No physics defaults are tuned to data.

Each case keeps immutable inputs, raw `truth.lh5`, `run.log`, `run.json`, and
`event-energies.csv`/`spectrum.csv`; the parent `comparison.json` summarizes tests
and uncertainties. Counts are normalized to all primaries, including zero-deposit
events. Spectrum bins are 0.5 keV and exclude zeros, which are separately counted.

Full containment uses a 1e-6 keV numerical energy tolerance, not a measured
photopeak-width window. No Fano, electronic noise, Li loss, shaping or ADC response
is included. Marginal Wilson 95% intervals and independent Newcombe-Wilson
intervals compare containment fractions; sparse histogram bins should not be
interpreted with Gaussian significance from the stored standard error alone.
A separate post-hoc two-sided Fisher exact family with Holm adjustment is also
reported; it does not turn the marginal intervals into simultaneous intervals or
establish equivalence. All original intervals/counts remain unchanged.

The saved 59.5 keV same-constructor control has a nominal difference interval
excluding zero; it is retained, not rerun until it passes. This finite-sample
control motivates independent-seed studies before declaring any model effect.
All constructor comparisons remain sensitivity diagnostics, not an accuracy rank.
The first six cases reproduce their earlier event-energy arrays byte-for-byte.
See [PHYSICS.md](../simulation/PHYSICS.md) for primary references and the separation
between radiation models, charge response and the owner's spectrum-only data.

## Nominal cryostat and actual Cs137 decays

`cs137.py` is separate from the frozen mono-gamma handoff. It imports the pinned
`stage.tg -> shield.tg -> chamber.tg` through native `G4tgbVolumeMgr`;
`cryostat_export` is an additional CMake target. Upstream bytes are hash-checked
and never edited. `cryostat_nominal.json` defines a nominal modular assembly
with canonical AK02/SAP22 solid, BN spacer and Al/polyethylene capsule.
**This is not a surveyed apparatus.** Global +y is above the curved cylindrical
end-cap, not an identified lab lid. Real capsule/holder/source dimensions remain
unknown; the JSON lists assumptions and omissions.

The imported cavity global translation is `[0,1.473,-3.710] mm`. Crystal global
translation `[0,1.450,0.290] mm` gives cavity-local `[0,-0.023,4] mm`; local +z
rotates to global +y. Existing indium top is cavity y `-0.523 mm`. The 0.5 mm
spacer centre is y `-0.273 mm`, so its top meets the crystal bottom. Native checks
cover composed poses, canonical volume/Inside probes, source containment and
recursive overlaps (10,000 samples/placement, fixed seed). The report lists all
materials, densities and placements. Sampling is not a proof of absence of
arbitrarily small overlaps. Any import/check failure blocks transport. Generated
volume names are unique for passive ledger registration; originals stay intact.

Run in `transport/` through the existing locked environment. These are prepared
commands; completed nominal geometry and integration checks are recorded in
`../PROGRESS.md`:

```sh
bash run.sh cmake -S . -B ../.local/m2a/cs137-build-v1 -G Ninja
bash run.sh cmake --build ../.local/m2a/cs137-build-v1 --target cryostat_export --parallel 2
bash run.sh python -B test_cs137.py
bash run.sh python -B cs137.py validate-probe --raw ../.local/peak-native-delivery/rdm-probe/truth.lh5 --model AK02 --events 20
bash run.sh python -B cs137.py prepare --model AK02 --output ../.local/cs137-nominal-check/AK02 --exporter ../.local/m2a/cs137-build-v1/cryostat_export --events 20 --seed 26092631
bash run.sh python -B cs137.py run --directory ../.local/cs137-nominal-check/AK02
bash run.sh python -B cs137.py extract --directory ../.local/cs137-nominal-check/AK02 --chunk-size 7
bash run.sh python -B cs137.py check-stream --manifest ../.local/cs137-nominal-check/AK02/stream/manifest.json
```

Repeat prepare/run/extract/check-stream for SAP22 in a fresh SAP22 directory.
Windows uses `transport\Run.cmd` with the same arguments from repository root.
The supervisor's local `run-transport-checks.ps1 -Name FRESH_NAME` runs serial
stages with separate stdout/stderr logs and exit receipts; optional
`-Stage Build|Tests|Probe|AK02|SAP22` selects a subset. No new adapter command
installs packages. Outputs must be new and below `.local/`, without linked paths.

The source is one zero-kinetic-energy Cs137 ion/event. Remage resets initial
decay secondaries to zero while retaining daughter lifetimes. Full always-on
Track output and float64 vertex/primary/step fields preserve both endpoints,
track links and zero-energy rows without clustering. Passive materials use the
native Scintillator scheme with optical physics off. Their registration also
applies the declared 0.01 mm sensitive production cut to those volumes; this is
explicit, not a convergence claim. Unsupported commands/schemas fail without
dropping fields. Receipts hash raw LH5, software/config/source, geometry/macro,
upstream originals and installed Cs/Ba decay/photon and ENSDF state data.

The ledger is **recorded material deposits only**. Stock Track output lacks
terminal escape/neutrino/full recoil closure: closure is null with missing terms
listed. Summed descendant kinetic energies are never called an energy balance.
No 662-keV ceiling or gamma-primary check is applied.

Only a finished extraction publishes `stream/manifest.json`, with kind
`cs137_decay_stream_v1`. JSONL chunks hold <=100 complete decays, including all
zero-Ge events. Global IDs equal original IDs `0..primary_count-1`. Records keep
all vertex/primary/track scalars, every Ge row including zeros, raw row identity,
raw/global/local positions, time, energy, parent links, material sums and photon
creation records. All passive rows/tables remain in hashed LH5. Round-trip
numeric serialization uses no rounding or sampling; changing extraction chunk
size preserves concatenated JSONL bytes. Reads require serial monotone event
blocks and are bounded by a block/event, not campaign length. Track IDs are
event-local. `iter_decay_chunks(manifest_path)` checks hashes and ID completeness.

Decay photons are PDG-22 tracks created by a saved process name containing
`RadioactiveDecay`, including photons missing Ge. Inclusive `[660,663] keV`
line-emission counts are separate from all emitted photons and accepted pulses.
Raw Ba PDGs/ancestry/times survive; excited/stable identity still needs checking
against installed data. A PDG suffix alone is not an isomer validation.

`group_deposits(steps, horizon_ns=100000)` sorts positive rows by time/raw row and
assigns each exactly once to `[origin, origin+horizon)`. It exports group ID,
origin and relative delays. Zero rows remain in the decay and create no pulse.
Delayed daughters use finite groups, never minute-long waveform allocation.
This is a **nominal isolated-window acquisition**: reset each group, truncate
its tail at the end and retain recovery/tail flags. Nearby deposits split by a
window boundary are flagged; continuous-state electronics is not claimed for
that split. No activity/live-time/pileup claim follows. Native consumers must
preserve these flags and parent/group IDs.

Synthetic tests cover zero events, delays, window edges, tiny positive energies,
identities, duplicate/missing rows, units/precision, interruptions, paths and
stable chunking. Original bare-probe validation is a clock/identity diagnostic.
Nominal AK02/SAP22 checks precede an accepted 500-decay pilot or 10k campaign;
the supplied check script only requests 20 decays per model.

The guarded Windows campaign entry and post-run comparison are documented in
[`tools/NATIVE_CAMPAIGN.md`](../tools/NATIVE_CAMPAIGN.md). A real 500-decay pilot
with positive Ge deposits has completed for both detectors; consult the current
handoff for larger-run status. All original failed runs and source versions remain
local evidence. This does not change the explicit nominal geometry or null full
energy-closure limitations.
