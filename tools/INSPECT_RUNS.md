# Inspect a saved local run without starting calculations

From the repository root in Windows PowerShell:

```powershell
.\Run.cmd status
.\Run.cmd inspect -Name RUN_NAME
.\Run.cmd inspect -Name RUN_NAME -Json
.\Run.cmd resume -Name RUN_NAME -DryRun
```

`inspect` checks supported small LBNL campaigns using PowerShell file reads only.
It does not import Julia, invoke WSL, install dependencies, create a run lock,
write a report, regenerate plots or start/resume any calculation. JSON mode emits
one object on stdout; wrapper diagnostics use stderr. Opening results is separate:
`open` may regenerate the local presentation index, but does not calculate physics.

This inspection is deliberately conservative. Success means a terminal saved run
passed the supported file/configuration checks; it is not permission to execute,
a runtime-readiness check or evidence of experimental accuracy. Missing, partial,
held/inaccessible-lock, source-incompatible and unstable states are reported as
blockers. An absent phase is not evidence of a successfully completed calculation.

A source mismatch can legitimately block reuse of an old completed campaign.
It does not require rerunning that campaign or editing its receipts. Original
results remain available for reading. Actual resume still acquires its own lock
and revalidates inputs; finer interrupted-stage recovery is separate future work.

## Validation and boundaries

The shared PowerShell checks require all 16 response artifacts (plus the failure
ledger when applicable), exact guarded or explicitly legacy source inventories,
byte sizes, parent/child bindings, histogram census, native settings, copied
profiles and independently reconstructed readout configuration. They check saved
receipts and current source compatibility; hashes are not authentication signatures.

`terminal_compatible` is only a terminal saved-state result. The expected native
seed is labelled as expected; blocked responses are not presented as verified.
A source mismatch can leave artifact/settings checks unfinished rather than proving
file corruption. A detected change during inspection invalidates the stable result.

Evidence: `.local/lowcode-inspect-v1/`. The corrected run passed 22 targeted tests,
including rehashed setting/inventory mutations, missing parent-bound children,
held/missing locks, linked paths, parsed JSON and no-write checks. The two original
positive-v2 outputs (four accepted groups per detector) were read and checked, not
recalculated. The source-only same-machine clone covered 24 candidate files and
correct missing-run/dependency reporting; it is not cold-machine reproduction.

The initial test attempt exposed an absolute-path joining bug; its failing log
and executed source were retained. Neither attempt generated radiation, solved
fields or recomputed native/electronics signals. Original 272 protected files
retained SHA-256, size and modification time.

The same original workflow and site-UX reviewers exchanged three scoped review
rounds and closed the implementation, with the recorded test evidence inspected
read-only. Final JSON output keeps the detector set as an array even for one
model. Broader electronics editing, interrupted-phase recovery and new detector
adapters remain separately scheduled work, not features of inspection.
