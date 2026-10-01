# Finite source-instance preparation contract (M11a)

`transport/scenario_prepare.py` is an opt-in developer adapter with only `check`
and `prepare`. It resolves separately versioned assets and instances, prepares
native-checked nominal geometry and a source macro, and records hashes. It never
runs radiation, fields, charge, calibration or readout. Existing Run.cmd, M10 UI,
Cs137 producers, native-stream readers, profiles, models and lockfiles are unchanged.

The finite registry supports the existing `lbnl_modular_nominal_v1` cryostat;
canonical AK02/SAP22; Cs137 point decay or one synthetic 662 keV gamma along global
`[0,-1,0]`; and `nominal`/`plus5mm` source poses. The point and unchanged aluminum
capsule/polyethylene fill move together to `[0,37.073,0.290]` or
`[0,42.073,0.290]` mm. The capsule axis remains global +y. Each preparation needs
its own native geometry acceptance; these are nominal engineering positions,
not an experimental survey. Source displacement +y and gamma direction -y are
separate settings. There are no free pose, material, orientation or clock controls.

Assets are under `scenarios/assets/`; four explicit example instances are
`scenarios/m11a-{ak02,sap22}-{cs137_point_decay_v1-nominal,mono_gamma_662_axis_v1-plus5mm}.json`.
The Python registry owns exact IDs, version 1, allowed fields and semantics.
Instance hashes bind asset bytes but cannot authorize a deliberately rehashed
semantic edit. Unknown/extra/duplicate keys, unsafe refs, unsupported versions,
nonfinite values and Boolean-as-number edits refuse before output or subprocess.
The tranche fixes count 20, planned radiation seed 26092631, and explicit
mm/ns/keV/deg/V/K units. The native overlap check uses 10000 samples and seed
26092632. A prepared beamOn command is an input, not an emitted event census.

Original model temperature is 78 K, contact 1/readout is 0 V, and contact 2 is
+500 V for AK02 / +700 V for SAP22. Check binds exact model/catalog/include/profile
bytes and reviewed metadata using only the Python standard library. It performs
no fresh YAML physics parse, private-upstream lookup, output creation, subprocess
or runtime lookup. Prepare independently calls the existing model parser in the
existing locked Linux environment. No 77 K override or carrier calculation occurs.

From the project root, use an explicitly selected **existing** Python interpreter:

```console
python -B transport/scenario_prepare.py check --config scenarios/m11a-ak02-cs137_point_decay_v1-nominal.json
```

No Python installation or PATH change is implied by that illustrative command.
The optional Windows bridge uses the existing Ubuntu-24.04 envelope. From the
project root, this prepares one new geometry and source macro only:

```console
transport\Prepare.cmd prepare --config ../scenarios/m11a-ak02-cs137_point_decay_v1-nominal.json --output ../.local/m11a-preparation/AK02-Cs137-nominal --exporter ../.local/m2a/cs137-build-v1/cryostat_export
```

The bridge's working directory is `transport/`, so arguments are relative to it.
It executes this fixed argument route, with no install/build/fallback:

```sh
"${PIXI_EXECUTABLE:-$HOME/.pixi/bin/pixi}" run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_prepare.py prepare --config ../scenarios/m11a-ak02-cs137_point_decay_v1-nominal.json --output ../.local/m11a-preparation/AK02-Cs137-nominal --exporter ../.local/m2a/cs137-build-v1/cryostat_export
```

Prepare requires all nine unchanged private upstream originals and the exact
existing 83872-byte exporter SHA256
`87b510882ed3f07b610895fddc93d7c3a4d16e8cf2b5a22d2d7994b31164266e`.
A missing runtime/exporter refuses. Only the native exporter is invoked, as a
fixed seven-element argument array with shell disabled. The generated 18-value
parameter file fixes crystal/cavity/spacer dimensions and varies only the finite
capsule/source center. No upstream text geometry is republished or reconstructed.

Exit zero alone does not accept a preparation. Independent checks require exact
report schema/Geant4 1132/seeds/sample count, strict Boolean flags, every generated
Inside probe, independent reference crystal volume, all 20 name/path/copy/material
associations, finite proper rigid transforms, material density/element fractions,
and every volume's overlap false. Original paths legitimately repeat for screwBar
placements; path plus copy identifies those placements. Copy number 1 legitimately
repeats for Ge, spacer, capsule and fill; global copy-number uniqueness is not a
requirement. The crystal and source/capsule/fill transforms match the requested
poses. Independent inverse-transform math uses global **mm** directly; it does
not pass mm into the existing helper that expects global metres. The emission
point must be strictly inside the 2.9 mm radius / 0.4 mm half-thickness fill;
a conservative 1e-12 mm arithmetic margin refuses a rounded-in boundary.
Overlap sampling still cannot establish absence of arbitrarily small overlaps.

Cs137 uses the unchanged report-driven macro helper. Gamma requires the exact
known helper boundary and Cs137 suffix, removes only the five known decay-only
lines, retains common scorer/precision/Track/Vertex/zero-row settings, and writes
one gamma GPS suffix with direction -y, Mono 662 keV, time 0 ns and number 1.
Scored deposits and birth/STEP records are future radiation quantities; this
preparation contains none and makes no trajectory/energy-closure claim.

Public configuration, selected assets and nominal geometry are parsed and hashed
from the same byte snapshots. Every checked-plan input digest must agree with the
first preparation inventory before any output or native dispatch; a mismatch
refuses without silently re-resolving the selection. The four retained v6 native
preparations remain original-version evidence after this binding-only correction;
their source pins are never rewritten as corrected-version results.

Every output root must be fresh and guarded below `.local/`. The adapter freezes
public/private inputs, source and exporter hashes before native launch, rechecks
them and generated inputs before completion, and retains failed logs/reports/
partial publications. A changed-source failure requires fixing/retrying the
derivative in a **new** root; it never authorizes repeating accepted radiation.
The new `scenario_source_prepared_v1` kind is deliberately rejected by the legacy
Cs137 stream reader. Stages explicitly state geometry_checked,
source_macro_prepared, transport_not_executed, charge_not_executed and
readout_not_executed. Unknown activity, energy closure, experimental geometry and
acquisition limitations remain explicit. Native preparation is not new-source
transport/full-chain acceptance, calibrated Li CCE or experimental validation.

`transport/test_scenario_prepare.py` uses pure configuration and mocked native
tests; retained fixtures are under `.local/m11a-preparation/mock-tests/`. These
tests do not execute Geant4, remage, Julia or installed environments. Later actual
geometry checks must be recorded separately, after source writers have exited.
M7a's accepted SAP22 chain is reused; M8/M9 still await the owner's second computer.
