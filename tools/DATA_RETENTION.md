# Permanent scientific data retention

The owner explicitly requires completed simulation data to remain available, so later response studies must not require radiation reruns. The following are permanent scientific outputs, even though their local directory is ignored by Git. They are NOT cleanup caches.

## Completed two-million-decay campaign

Preserve `.local/cs137-1m/` in full. It contains 100 completed 10,000-decay chunks for each of AK02 and SAP22. In particular retain `config.json`, `config.sha256`, `runtime.json`, `inputs/`, `COMPLETE.json`, every `DONE.json`, and the referenced attempt's `compact.h5`, `truth.lh5.gz`, `archive.json`, `transport.json`, `run.mac`, `geometry.gdml` and logs. Keep failed attempts and diagnostic evidence too.

`truth.lh5.gz` is the lossless original transport container, NOT a sampled event summary. The old temporary uncompressed copy was removed by the original launcher only after archive round-trip verification and durable checkpoint publication. Restoring it from gzip does not require rerunning Geant4. `compact.h5` retains every primary's scalar results, all Ge steps and selected detailed particle records; it does not replace the complete archive.

The September 27 preservation audit verified all 200 checkpoints, all compressed-file hashes, and the SHA-256/byte count of each decompressed original. It also read all compact HDF5 datasets, verified event ranges, photon denominators and Ge energy sums, and found no modified/deleted original files. Evidence: `.local/million-analysis/preservation/audit.json`. A small `reproducibility-inputs.zip` beside it preserves exact input files, completed receipts, recorded source dependencies and model snapshots.

Keep the old `.local/peak-native-delivery/cs10000-v2` baseline and the failed strict `cs10000-v1`, their source geometry caches, prior native diagnostics, and versioned canonical models unchanged. Future analysis outputs belong in a distinct folder with their own provenance, never over the originals.

These files and the reproducibility snapshot currently occupy the same physical computer. Hash verification and a same-disk snapshot are not an independent off-device backup. Do not claim that Google Drive has synchronized unless separately verified.

## Permitted follow-up

Read completed data, regenerate derived spectra, change explicitly versioned readout settings in NEW runs, or recover a raw archive into a new analysis scratch location. Preserve event, chunk and detector identities. Do not invoke `prepare`, `run`, `Resume.cmd` or a radiation generator simply to inspect completed data. No automated deletion of the protected campaign is authorized.
