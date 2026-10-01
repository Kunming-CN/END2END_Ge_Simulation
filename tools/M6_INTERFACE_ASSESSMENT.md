# M6: keep the existing readers

Assessment: 2026-09-30 local. M5 remains closed. The optional M6 decision is to
**keep the existing backend and readers**. Installed official LH5 decoding is
compatible with the checked saved records, but replacing a low-level reader
does not remove the project's required identity, census, units, provenance and
geometry checks. No integration or environment change is justified by this trial.

## What was actually checked

The existing detached transport environment contains Python 3.13.15, remage
1.1.0, legend-lh5io 0.2.7, legend-pydataobj 2.0.3, pygama 2.6.2, h5py 3.16.0
and NumPy 2.5.3. These were inspected through its existing interpreter without
installation, bytecode generation or changing global settings.

The earlier proposed reboost grouping / simflow dry-plan operation is deferred:
those packages are unavailable in this environment. A smaller **reader-only**
trial was performed instead. It is not acceptance of either missing operation.

One preserved earlier AK02 10k Cs137 raw LH5 file (37,732,755 bytes) supplied a
three-primary comparison: 0, 213 and 3645. Selection was declared before the
trial: the lowest true-zero ID, the lowest positive ID also containing a
zero-energy Ge row, and the ID with the most Ge rows, breaking ties by ID.
Selection scanned the existing reader's 3,242 Ge scalar rows and auxiliary
identity columns. All original rows for those primaries were selected; none
were truncated.
The complete 10,000-primary vertex-ID census and recorded primary count were
retained separately from the sparse deposition tables.

Official `lh5.read` agreed with the original raw HDF5 datasets on every selected column
in 14 nonempty flat tables: inventory, dtype, shape, numeric bytes and attributes,
including units. Eight empty selections were retained separately from the raw
identity ledger; official empty-table decoding was not tested. Original physical
row indices were retained. The existing project Ge reader supplied role selection
and the Ge truth ledger; a separate check matched all selected Ge physical row
indices to the indexed HDF5 selection. The selected Ge table has
76 rows including six zero-energy rows; birth records, parent/track/particle
identities, all selected passive step tables and UID aliases were checked too.
Primary 0 retains no Ge steps. Primary/step/birth times remain separate, with
delayed daughter records unchanged. Coordinates remain the recorded global
metres; no local transform or geometry validation was performed by this trial.

Input, model and relevant source SHA-256/size/mtime checks passed before and
after. Local evidence is `.local/m6-interface-v1/`, including the observed
inventory, predeclared acceptance, trial source/results and reviewer records.
Private source paths and raw records are deliberately excluded from this report.

## Why no replacement

The official library provides useful general LH5 object decoding and indexed
reads. It does not enforce the project's complete primary ledger, raw row
identities, source bindings, units policy or coordinate mapping. Keep the existing
strict rejection of inconsistent raw columns and units before using decoded
output for a handoff.
Successful object decoding is insufficient for radiation-to-charge handoff.

The current small flat-table reader is already bounded and preserves original
scalar records. Adopting another entry would still require the same validators
and conversions. This trial demonstrates interoperability without establishing
a maintenance saving. Keep the existing path; revisit an official interface only
for a separately scoped use that removes identifiable duplicated work.

The one combined comparison took about 0.86 seconds after imports and input
inventory/hashing. This is a single measured comparison, not an official-reader
speedup or a promised runtime. No radiation, field, native charge, calibration
or readout was run. No original campaign output or numerical source was changed.

This result does not validate event grouping, local coordinates, Li collection,
detector accuracy, electronics, experimental agreement or fresh installation.
It does not generalize to reshaped/jagged or arbitrary external LH5 files.

Official references: [LH5 API](https://legend-lh5io.readthedocs.io/en/stable/api/lh5.html)
and [remage output semantics](https://remage.readthedocs.io/en/stable/manual/output.html).

## Next scope

M7 remains the next main feature: select one useful detector/scenario combination
with complete inputs, check its geometry and transport/SSD/readout mapping, then
define a bounded positive example. Fresh-machine acceptance still waits for the
owner's second computer. M3 and M8/M9 remain deferred.

Website link and information organization is a separate saved-display task in
[the roadmap](ONBOARDING_EXTENSIBILITY_PLAN.md#website-links-and-information-organization).
This assessment does not rebuild or publish the website.
