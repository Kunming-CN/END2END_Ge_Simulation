# Finite gamma transport contract

`transport/scenario_transport.py` adds a separate twenty-primary gamma transport
and lossless event-stream stage. It accepts only a fresh current-version M11a
preparation of canonical AK02 or SAP22 with `mono_gamma_662_axis_v1` and the
`plus5mm` capsule/source pose. The two candidate cases have a ceiling of forty
initial primaries in this milestone. This does not rerun Cs137 science or perform
SSD, field, calibration or readout calculations.

From the existing project `transport/` directory, use the existing locked Linux
runtime:

```text
pixi run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_transport.py check --prepared ../.local/m11b-gamma20-v1/AK02
pixi run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_transport.py run --prepared ../.local/m11b-gamma20-v1/AK02
pixi run --locked --no-install --manifest-path ./pixi.toml python -B ./scenario_transport.py extract --prepared ../.local/m11b-gamma20-v1/AK02
```

`Gamma.cmd` provides the same opt-in entry through the existing Ubuntu-24.04 WSL
distribution and `gamma.sh`. It uses the selected existing Pixi executable and
refuses a missing runtime; it does not install, rebuild, change PATH, use `eval`
or fall back to another environment. Substitute `SAP22` for the second case.
Preparation is still the separate `scenario_prepare.py` entry. Fresh preparation
and output roots are required; the four preserved M11a v6 preparations remain
evidence of their own version and must never be rehashed into the v7 version.

Check re-resolves the finite public instance/assets and independently verifies
their semantics and pinned model/include/catalog/profile bytes. Same-read JSON
snapshots bind parsed prepared/report/resolved records to their SHA witnesses;
public config/assets/nominal snapshots bind the complete checked plan to the
initial inventory before dispatch. Exact macro, canonical contour, parameters,
probes, native report, material mapping, original 78 K and 0/+500 V or 0/+700 V
contacts are checked. Rehashed Boolean schema versions, changed source direction,
unsupported summaries and altered unknown/omitted/unscored labels fail. The new
module pins the accepted preparation adapter version and preserves all stage
hashes instead of rebasing a changed source. Check produces no output and starts
no subprocess.

Run uses one thread, seed `26092631` and the retained M11a macro: PDG22, one
662 keV gamma per primary, global direction `[0,-1,0]`, source time zero,
point `[0,42.073,0.290]` mm and exactly twenty primaries. The capsule/source
displacement is along global +y; gamma direction is along global -y. Livermore EM,
the existing 0.1 mm default and 0.01 mm sensitive cuts, all scorers, double
precision Track/Vertex outputs and zero-energy-hit retention remain fixed.
Before dispatch it verifies the recorded executable bytes and versions of the
existing remage 1.1.0 and Geant4 11.3.2 runtime, then records Python/dependency
versions. The installed G4LEDATA directory must be inside the selected prefix
and its conda metadata must identify the locked EMLOW 8.6.1 package/build/archive.
A sorted manifest records every regular file's relative path, size and SHA256,
with a finite 100,000-file/2 GiB ceiling and measured hashing wall time. The shared
paired manifest preserves installed byte identity; it does not claim these are
the exact files accessed by Geant4. Input, generated artifact, producer and data
hashes are checked again before completion. A failed attempt keeps its raw file,
log and failed receipt; a completed or failed run is never overwritten/replayed.

The reader reuses `cs137.field`, `table_rows`, `event_rows`, `Cursor` and
`step_aliases` only. It never changes the legacy ion constant or invokes the
legacy decay producer/reader. Native identities are integers, floating columns
are float64, raw positions/surface distances are metres, native primary/track
energies and momentum are MeV, deposits are keV and times are ns. The explicit
metre-to-local-mm transform uses `handoff.to_local`; each Ge deposit and both
STEP endpoints must belong to the canonical contour. Every event retains one
vertex/primary, a gamma root birth at zero time and the configured point, all
Track births (including the native primary process sentinel), valid secondary
process names, complete acyclic parent links and matching deposit ancestry.
The fixed runtime also supplies one global `detector_origins` row for the Ge
scheme. Its flat string/float64-metre schema, single `germanium` name and global
translation must match the checked crystal transform within 1e-10 mm. It has no
event ID or rotation metadata and is retained once, with raw table/column
attributes, in the manifest; it is not expanded into nineteen material origins.
Foreign/missing/repeated IDs, missing material tables, wrong aliases, precision,
units, momentum, clock or nonfinite values fail even if a native exit code is zero.

Extraction creates a fresh `stream/` with one twenty-event JSONL chunk and the
new typed `scenario_gamma_event_stream_v1` manifest. IDs are exactly 0..19;
true-zero events and zero-energy raw rows remain present. Every scalar column
and physical `raw_row_index` of vertex/particle/track/process and all nineteen
scored material tables survives, as do native UID aliases, material energy sums,
surface distances, the global Ge-scheme origin and derived local Ge positions.
No sampling, event threshold,
decay-family grouping, activity estimate, full energy-closure claim or synthetic
raw quantity is introduced. The unscored world, escape energy, nominal geometry
and low statistics remain explicit. Track births and scored STEP chords are not
complete trajectories across unscored material. The manifest binds prepared,
run, raw LH5, producer, source asset, model and serialized chunk hashes. Failed
partials remain. A changed-source failure retains its incomplete bundle; a later
reviewed saved-data recovery path may produce a fresh derivative after a source
freeze. This CLI does not provide that recovery path. Radiation remains untouched
and is never replayed merely to recover an extraction failure.

Charge and readout statuses remain `charge_not_executed` and
`readout_not_executed`. The existing `native_stream.jl` Cs137 reader intentionally
does not accept this kind. A later bounded coupling adapter must explicitly
consume the gamma kind and initial-primary clock/ID policy, preserve all rows and
zeros, and use the existing native helper without relabeling these as decays.

Focused synthetic HDF5 and mocked-dispatch tests require the existing locked
NumPy/PyYAML/h5py environment:

```text
pixi run --locked --no-install --manifest-path ./pixi.toml python -B -m unittest discover -s . -p test_scenario_transport.py -v
```

Fixtures and all receipts remain under `.local/m11b-gamma20-v1/`. Unit tests do
not call native geometry, remage, Julia, SSD or readout. Ordinary static website
publication does not acquire this HDF5 dependency or run transport.
