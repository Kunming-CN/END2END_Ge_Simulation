# Selected HDF5 to native pilot

`native_hdf5_bridge.py` exports checked small inputs from permanent completed
`.local/cs137-1m/` compact HDF5 and the completed million analysis. It reads only
selected chunks and saved classifications, without extraction, reanalysis,
Geant4, installs or upstream access. Existing source and science files stay frozen.

Default selection includes all 20 deduplicated saved representative primaries,
one actual zero-Ge primary per model, and the saved SAP22 two-group primary.
The two original cs10000-v2 native failures are separate diagnostic namespaces,
with original event/raw-row seed identities. The contract retains all selected Ge
rows, including zero-energy rows, every original raw column, global metres,
transformed local millimetres, exact deposition times, groups and delays.
Every selected row is compared back to HDF5. Raw archives remain read-only references.

Full million input-population counts, selected counts and omitted counts are
separate. Nonselected response is null. A zero-Ge primary has no pulse; failed
native transport has unknown charge/readout, never an invented zero waveform.
The original all-primary scalar ledger remains the full-population reference.

Run from the project root with existing Windows executables (no WSL):

```powershell
& 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe' --disable-registry --no-mpi -B tools/test_native_hdf5_bridge.py
julia --startup-file=no --threads=2 --project=simulation simulation/test_native_bridge_pilot.jl .local/native-bridge-pilot/test-contracts-001
& 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe' --disable-registry --no-mpi -B tools/native_hdf5_bridge.py --export .local/native-bridge-pilot/contracts-v1
& 'C:\Program Files\ParaView 6.1.1\bin\pvpython.exe' --disable-registry --no-mpi -B tools/native_hdf5_bridge.py --run-pilot .local/native-bridge-pilot/contracts-v1 --output .local/native-bridge-pilot/pilot-v1
```

Tests print the actual newly reserved fixture directory; pass that path to Julia.
All output directories must be new. Failed evidence is retained. Freeze source
before final export and do not edit while the consumer runs. `--verify DIR`
rechecks the exporter pins and all selected raw rows. Optional
`--select AK02:0,2594 --select SAP22:0,11163` replaces the million selection with
1..64 original global IDs per detector; old diagnostic cases remain separate.
Sorting selection cannot change seeds. Global ID, not chunk-local ID, feeds the
unchanged SHA256 parcel-seed helper. Model/campaign namespaces identify runs;
historical diagnostics deliberately reuse their old seed family and IDs.

The Julia adapter includes unchanged `native_response.jl`, preflights both
detectors and all inputs, writes both profiles/resolved configs before solving,
then solves once per detector and reuses fields across both namespaces. It calls
strict `NativeLiExample.native_event` through the existing exact allowlist in
`NativeResponse.native_attempt`. It uses pinned 77 K, +500/+700 V, 16 equal-energy
parcels, 2 ns, 10 us cap, diffusion on, zero-field termination off, no repulsion,
and the unchanged signed synthetic profile with independent injection calibration.
Only expected primary count varies in resolved configs. No per-event gain or sign
rectification is introduced. The 100 us isolated electronics window is distinct
from the 10 us drift cap and from the analog sample grid.

Each namespace has a primary/pulse scalar ledger, exact signed charge CSV, bounded
readout trace JSONL, endpoint JSONL and explicit native failure JSONL. Identity
records bind original chunk/local/global primary IDs, raw LH5 hash and row IDs.
The copied contract supplies exact original raw rows for all results. `run.json`
retains pre/post field fingerprints, calibration, versions, source hashes,
separate native/readout/field timings, flags and artifact hashes/sizes. The top
terminal receipt and summary describe completion, including native failures.

This is a selected engineering demo, not resumable million-response production,
calibrated Li CCE, a measured spectrum, physical energy resolution, source survey
or convergence claim. Caps, contacts, negative charge, thresholds and gates remain
independent diagnostics. The adapter checks a 600-second budget between calls.
The `--run-pilot` launcher runs Julia with `--startup-file=no --threads=2
--project=simulation`, enforces a hard 600-second compute/export deadline and
a separate 180-second startup/preflight limit, and saves child exit/log evidence.
Only child thread-pool variables change. No retry is automatic. Direct Julia
invocation is available with `simulation/native_bridge_pilot.jl --input DIR
--output NEW_DIR`, but needs an external watchdog for a stalled native call.
