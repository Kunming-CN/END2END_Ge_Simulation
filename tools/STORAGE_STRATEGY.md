# Million-decay storage strategy

The owner approved a Geant4-only, default-angle Cs137 campaign after the saved 10k runs. Old geometry, materials, production cuts, source and all old outputs stay unchanged. This document distinguishes a new storage layout from a physics change.

## Primary references and decisions

The [remage output manual](https://remage.readthedocs.io/en/stable/manual/output.html) recommends retaining HPGe steps for later detector-response processing without repeating particle transport. Its event-energy filter can remove records across multiple output schemes; pre-clustering can merge steps/track identities. Neither is enabled here merely to save space. The Calorimeter scheme's documented float32 energy is not a silent replacement for the existing float64 material ledger.

The [h5py dataset documentation](https://docs.h5py.org/en/stable/high/dataset.html) provides lossless gzip compression, byte shuffle and Fletcher32 chunk checksums. The compact analysis files use lossless filters, not floating-point scale-offset or rounding. Original units, IDs, raw row maps, deposition delays and selected-step float precision must survive.

Use two tiers: compact per-chunk HDF5 for all-primary scalar accounting and complete Ge-hit event records; separate byte-exact compressed original LH5 archives for recovery of ANY originally recorded detail. Do not explode every event into browser JSON/CSV. A future missing analysis field should be recovered from the raw archive rather than trigger another radiation simulation.

A local read-only measurement on the old 10k/model files found 37,732,755 / 38,121,040 raw bytes and 36,359,092 / 36,747,520 gzip bytes, with verified decompressed SHA-256 identity. The raw format was already compact: gzip alone saves little. Extrapolation of this archival tier to 1M/model is roughly 7.3 GB total, not a guaranteed capacity result; compact outputs and logs add space. The major avoided growth is duplicated full-event JSON, CSV and millions of browser trajectories, not a claim of spectacular raw compression.

An uncompressed temporary file from a NEW successful chunk may be removed only after its lossless archive and compact output have been independently verified and durably recorded. Original 10k files and failed attempts are never cleaned up by this policy. Incomplete writes are not completed checkpoints. A small tested chunk limits the work lost to a crash.

No scheme reconstructs world-air paths absent from the original output, or turns radiation tracks into SSD charge transport. No new Fano/electronics model, geometry calibration or source-direction bias is implied by storage changes.
