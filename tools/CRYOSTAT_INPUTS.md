# Cryostat source-input verification

`transport/cryostat-input-ledger.json` is a project-authored inventory of nine
recorded LBNL source files and selected facts. It publishes relative locators,
provenance and limitations, not upstream TG/MAC files or private evidence.
The fixed original manifest SHA-256 is
`5967d5d0f8500a40f704bf653be2dc1a0f69e77239f643a8f7140533c9201e2a`;
the recorded upstream commit is `1ff3371e0afb804115773af0541b3e56bd660f8c`.
Hashes establish byte identity, not authorship, physical accuracy or experiment.
The existing pinned-tree record found no explicit license file; this milestone
does not make a current licensing claim or grant redistribution permission.

Run the standalone checker from the project root with the existing Python:

```text
python -B tools/check_cryostat_inputs.py
python -B tools/check_cryostat_inputs.py --check-local --json
python -B tools/test_cryostat_inputs.py
```

The default mode reads only the public ledger and original provenance manifest.
It verifies curated metadata integrity without reading private TG/MAC inputs.
`--check-local` additionally reads exactly the existing nine cached originals
under `.local/transport/LBNL`, verifies their recorded sizes/hashes and checks
finite selected raw directives. Missing private inputs fail this explicit mode.
The CLI writes nothing and calls no adapter, producer, subprocess or solver.
Tests keep temporary fixtures under `.local/m11e-cryostat-inputs-v1`; they use
existing original inputs for the explicit local cases.

Strict JSON rejects duplicate keys, nonfinite numbers and invalid field types.
The original manifest pin and an independent reviewed metadata digest reject
changed source identities, support or facts even if edited metadata is rehashed.
That digest is a maintenance freeze, not a signature or support certificate.
Changing reviewed facts requires a separately reviewed source update. Local
reads reject traversal, unknown includes, symlinks and Windows reparse points.
The finite lexical checks do not evaluate expressions or construct geometry.

| Original variant | Entry and include closure | Status |
|---|---|---|
| Modular | `stage.tg -> shield.tg -> chamber.tg` | `supported_existing`, only through the current nominal adapter |
| Monolithic | `LBNLcryostat.tg`, no includes | `candidate_input_only` |

Both original variants have a 67.7 mm nominal cavity diameter. The monolithic
input has dimensions; its independent native import, solid/volume census,
material/source/transform checks and event mapping are unfinished software work.
Surveyed experimental crystal/source/holder poses, actual capsule/active-layer
inputs and lid orientation remain separate unknowns. No larger cryostat or
GeGI installation is supplied. Nominal and plus5mm source poses use the same
modular cryostat.

The existing backend stays fixed to `stage.tg` and its separate native
20-volume/copy/material/ancestry/transform/source checks in
`transport/scenario_prepare.py` and `cryostat_export.cc`. Its original detector
and wings from `planar4wings.tg` and standalone source from `Am241.tg` are omitted
by that adapter. A new or rehashed ledger cannot add executable support. This
milestone runs no native checks and establishes no as-built, overlap, efficiency,
charge-transport or experimental acceptance.

TG length values use parser-default mm, angles degrees and density g/cm3 unless
an explicit unit suffix is supplied. The selected TG facts have no explicit
unit suffix: `$in` references the raw parameter `in=25.4`, rather than a unit
token. Named raw lengths and solid extents are distinct. For example, modular
`Lec=165.5` mm gives `endCap` axial full length `Lec-Tfl=155` mm, while its hollow
full length is 152.46 mm. Monolithic `Vacuum` has axial full length 153.73 mm.
BOX inputs are half-lengths; TUBE inputs are radii and axial half-length. Selected
placement expressions remain raw parent-frame expressions; the checker neither
evaluates their rotations nor claims their experimental accuracy.

The original `LBNLcryostat.mac` explicitly selects gamma primaries at 59.5 keV,
with mm position tokens and confinement to case-sensitive `Active`. Its actual
geometry material is `G4_Au`; the `AmO2` material definition is unused by volumes.
The decay-physics constructor and filename do not turn the explicit gamma
primary into an Am241 decay. Modular `Am241.tg` defines lowercase `active` in a
separate source locator; these volume names are not interchangeable.

Format references, checked 2026-10-01: the official
[Geant4 text-geometry manual 1.0](https://cern.ch/geant4/collaboration/working_groups/persistency/docs/textgeom.pdf)
documents default units and BOX/TUBE parameters; the official
[GPS command reference, Book for Application Developers 11.4 (doc Rev11.4)](https://geant4.web.cern.ch/documentation/dev/bfad_html/ForApplicationDevelopers/GettingStarted/generalParticleSource.html)
documents particle/energy/position settings and physical-volume confinement.
These format references are distinct from the project's pinned Geant4 11.3.2
runtime; no runtime acceptance was repeated for this inventory.
