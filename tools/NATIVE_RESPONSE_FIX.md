# Native response correction and resumable processing

## Confirmed cause, not a speculative RNG explanation

In pinned SSD 0.11.8, ChargeDrift.jl allocates path storage with `undef`. If floating-boundary projection exhausts 1,000 trials, `_check_and_update_position!` marks the carrier done and continues without writing its current path slot. The returned path includes that slot. Uninitialized coordinates can look valid or invalid depending on allocation history; waveform generation previously preceded the endpoint check.

The same saved SAP22 event8413, raw row2694, parcel1, step23 returned exactly either of two arbitrary prefilled sentinels (+12345 or -98765 metres). The last valid position and field fingerprints were identical. This proves an unwritten-row defect. The old mixed-pilot finite response is not trustworthy; it remains preserved as historical evidence, not silently replaced.

`simulation/native_boundary_guard.jl` is an explicitly selected process-local guard. It verifies the exact upstream file hash, changes only that exhausted branch to throw a typed numerical failure before waveform calculation, and leaves installed package files and old project helpers untouched. It does not invent a terminal point, assign zero charge, or repair physical surface transport. Failed-group truth and identities remain; native/readout quantities are null. The latest-world wrapper prevents Julia world-age from bypassing the guard.

Fresh-process tests passed26 assertions: the bad case fails identically three times, successful control3815 is identical before/after allocation perturbation, unexpected exceptions propagate, and original fields/package bytes are unchanged. Sentinel proof and logs are saved under `.local/native-response-fix/`.

## AK02 event3950: cap hypothesis tested and rejected

The same original carrier trajectories were compared at10 and20 microseconds. Each electron and hole RNG starting state was captured/restored separately; all path AND time prefixes were required identical, avoiding a changed electron history perturbing the hole stream.

| Event | Verified carrier prefixes | Induced10us (keV-equiv) | Induced20us | ADC change | Conditional remaining bound (keV) |
|---|---:|---:|---:|---:|---:|
|3950|1600|59.16911716880672|59.16911716880863|0|0.005835676684335932|
|2594|1216|661.604091763961|661.6040917639672|0|0.01450185969984603|

The bound uses the native ConstantLifetime update, actual inactive-region classification and surviving mobile charge; it assumes no detrapping and a bounded future weighting potential. It is not recoverable charge or calibrated CCE. The large3950 deficit is not explained by the tested10us cutoff. Its near-outer-surface deposits and many holes collected at the outer contact, together with the existing1us inactive lifetime, remain part of the specified model. No physical parameter was tuned and charge was not forced to661.657keV. Cap flags remain visible.

## Record-mode production boundary

The full source campaign is already complete: `.local/cs137-1m/` contains two million initial decays. This new stage processes only the23,693 positive pulse groups while binding the original all-primary HDF5 ledger, including zeros. It never launches Geant4, repeats source analysis or solves fields again. Exact serialized field states from the bounded diagnostics are checked against the preserved field fingerprints and independent injection calibration.
Each pulse group is committed as an exact Julia binary containing signed charge, endpoints, raw event/group provenance, readout diagnostics and bounded traces. A flushed/synchronized atomic result precedes its checksum-bound DONE receipt. Resume validates identities, settings, source hashes, the actual Julia project/manifest, input hashes and caches. A complete result interrupted before DONE is recovered without computation. A missing/corrupted committed result aborts rather than silently rerunning it. Partial files and previous attempts are retained.

Windows exclusive handles prevent simultaneous native workers. The detached launcher records numeric child exit codes and reconciles only its matching private project owner. Closing the browser or chat does not stop the computation. Power loss can require recomputing only an unfinished group; completed results remain. The Julia binary format requires the recorded Julia/SSD environment to read; original HDF5/LH5 remains unchanged.

The real7-group checkpoint pilot completed5 successes and2 explicit historical numerical failures, including both old controls. It paused after2 groups and resumed the remaining5: the first4 result/DONE files retained identical bytes AND modification times. Metadata-only review corrections added internal serialized-identity matching and actual-project/manifest checks, covered by17 final checkpoint assertions. Six detached-launcher tests passed.

Use the existing Windows environment from the project root:

```powershell
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/prepare_native_batch.py --output .local/cs137-1m-native
& 'C:/Program Files/ParaView 6.1.1/bin/pvpython.exe' --disable-registry --no-mpi -B tools/native_response_launcher.py start .local/cs137-1m-native
```

Preparation refuses an existing directory. Never repeat it after a completed preparation; resume with the launcher only. `progress.html` and `progress.json` in the prepared folder track committed groups, numerical failures, accepted ADCs and an estimated remaining time. `STOP_AFTER_GROUP` requests pause; remove only that marker before resume. Final status can be `completed_with_native_failures`: this is engineering workflow completion with unknown responses retained, not zero numerical failures or calibrated detector efficiency.

The two existing agents separately reviewed execution-state integrity and carrier physics, exchanged findings, requested latest-world execution and two checkpoint/environment checks, and reviewed the resulting tests. Their approval does not establish experimental agreement or global Li/PDE convergence. No such global study was started.
