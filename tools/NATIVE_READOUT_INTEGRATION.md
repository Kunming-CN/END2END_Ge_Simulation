# Bounded new native charge to readout recovery (M5b integration)

`Run.cmd native-readout -Name NAME` generates new native charge for original AK02
IDs 0, 2594, 3950 by default, then runs the existing fixed-injection calibration and noiseless
readout functions. This deliberately selected engineering cohort contains three
primaries, one true zero, two nonzero groups and 91 original deposition rows.
It is not a spectrum/efficiency measurement or calibrated Li CCE result.

```powershell
.\Run.cmd native-readout -Name example -DryRun
.\Run.cmd native-readout -Name example -StopAfterGroups 1
.\Run.cmd native-readout -Name example -Resume -DryRun
.\Run.cmd native-readout -Name example -Resume
.\Run.cmd native-readout -Name selected -PrimaryIds "0,176,457" -DryRun
.\Run.cmd native-readout -Name selected -PrimaryIds "0,176,457"
.\Run.cmd native-readout -Name selected -Resume
```

Optional `-PrimaryIds` accepts one quoted CSV of canonical decimal IDs from the
current checked AK02 `cs137-1m` transport contract/cache. It preserves request
order, original identities, seeds, deposition clocks and every raw row, including
zeros. Grammar, uniqueness, membership and the limits of 8 whole primaries,
4 pulse groups and 100 complete raw rows are checked before runtime work or output
creation. Zero-only selections refuse. Unknown or malformed selections never
fall back. The selected 0/176/457 example has one true zero, two groups and
61 raw rows, including four zero-energy rows. It is an engineering example.

The immutable manifest binds the effective selection. Resume verifies its INITIAL
binding, rebuilds the plan from the original checked inputs and validates saved
stages. Any explicitly supplied PrimaryIds on Resume refuses, including an
identical list. Omission retains the default cohort and default-mode restrictions;
only the native-readout Julia adapter opts into selected events, with independent
identity, namespace, correspondence and resource checks before cache loading.

One output root is `.local/native-readout-integration-v1/implementation/outputs/NAME`.
Names use 1..24 letters/digits/underscores/hyphens and must fit the Windows path
bound. Existing names require Resume. StopAfterGroups counts newly committed
**electronics** groups (1..2); native charge completes first. Original charge-only
and saved-charge replay modes retain their defaults.

The fixed native settings, source/cache/model bytes, full original primary/row
ledger and frozen `simulation/native_readout_profile.json` are pinned separately.
No profile/physics overrides are accepted by this entry. Calibration uses the
existing synthetic injection, never event truth. Signed charge/current/voltage,
negative segments, native step/endpoint flags and rejected energy nulls survive.
The analog grid is not a waveform-digitizing acquisition. Partial collection and
step caps remain visible; electronics acceptance does not establish collection.

Charge, calibration and electronics each use existing immutable COMMIT receipts
and separate witnesses. Mandatory progress records bind the manifest and expected
and completed identity lists/counts for every stage. Lost/corrupt reported commits,
missing progress, changed source/cache/runtime, and independently rehashed config
changes refuse before numerical work. Valid commits newer than progress remain
reusable. Complete requires all three stages and the whole primary/zero ledger.
Completed resume and dry-run are read-only and never resolve/probe/start Julia.

Native `charge.json` and exact signed scalar/CSV adapter are co-committed in
`charge/KEY`; `charge/KEY/signals.csv` retains all 5,002 native samples/group.
Complete scalar records and bounded display traces are in `electronics/KEY`:
the accepted host run saved 600 display points/group from 50,000 internal analog
samples/group. Independent calibration is in `calibration/AK02`, and the final primary ledger in
`worker/AK02/scalars.jsonl`. Truth deposits remain separate from reconstructed
energy. Failures retain attempts/logs. Native unknowns remain null where the
existing record policy is exercised by fixtures; this fixed entry uses strict abort.
Uncommitted canonical data, missing witnesses, incomplete initialization and final
data without COMPLETE are conservatively refused. No orphan adoption or automatic
recomputation of missing accepted science is provided.

Implementation modifies only optional inventory/session adapter seams; exact
native and ReadoutProfiles numerical functions and dependency locks are unchanged.
Prior accepted outputs retain their original base-HEAD provenance, not the new
source identity. Source snapshots of modified native adapters remain in the new
implementation evidence. They are not migrated, rebased or declared corrupt.

The coordinator runs the opt-in host harness **after all writers exit** with an
explicit new source freeze. It creates exactly two new outputs: uninterrupted and
driver-death/resume. The death is injected after verified first charge commit and
before ACK, then the same output pauses after its first electronics commit and
resumes electronics only. Actual `group_ready` log records count executed work;
session requests are separately labelled planned work. Four native calculations,
one calibration per output, exact deterministic semantic equality, immutable
hash/size/mtime preservation and no-op behavior are required. Timings and the digest
of run-specific calibration timing bytes alone are excluded from comparison.
Existing M4b validation tolerances are unchanged; cross-run equality is exact.

Software fixtures mock both numerical stages; static import-scope checks do not
establish Julia parsing/loading. Actual host evidence and independent AI reviews
remain required. No original radiation/native campaign, field solve, packages,
PATH/global settings or publication is changed by this route.

The maintained software tests and host harness are
`tools/test_native_readout_integration.py`. Generated fixtures, logs, partials,
freezes and numerical outputs stay under
`.local/native-readout-integration-v1/implementation` for historical integration,
or `.local/m5-close-v1/implementation` for this final selection task. The coordinator's local
`run-host.ps1` invokes that maintained source with an explicit freeze. Select the
exact current source receipt named in the current implementation/coordinator
handoff for each future host test, after its writer exits. A candidate source
freeze is not actual-host acceptance. Preserve historical freezes, sources,
results and receipts with their original source pins; a later source correction
does not rebase earlier valid host evidence.
