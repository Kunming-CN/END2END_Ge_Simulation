# Saved-charge group checkpoints (M5a)

This opt-in mode creates a **new synthetic electronics derivative** from complete
saved signed charge. It imports charge; it does not produce new SSD charge.
Native-production checkpoints (M5b), hardware/noise fitting and immediate emergency
cancellation are outside this slice. Existing one-shot M4b commands keep their behavior.

```powershell
.\Run.cmd replay-readout -Name SOURCE -ReplayName NEW -Detector AK02 -CheckpointGroups -DryRun -Json
.\Run.cmd replay-readout -Name SOURCE -ReplayName NEW -Detector AK02 -CheckpointGroups -StopAfterGroups 1 -Json
.\Run.cmd replay-readout -Name SOURCE -ReplayName NEW -Detector AK02 -CheckpointGroups -Resume -DryRun -Json
.\Run.cmd replay-readout -Name SOURCE -ReplayName NEW -Detector AK02 -CheckpointGroups -Resume -Json
```

`-CheckpointGroups` is required for `-Resume` and `-StopAfterGroups`. The bound is
1..400 newly completed groups **in this command**, counting saved native failures
as groups. It stops after a complete verified commit boundary; earlier committed
files are preserved. Without a bound it finishes the remaining expected groups.
A killed child can leave the current stage incomplete. This is a cooperative
boundary stop, not a general GUI stop or immediate cancellation guarantee.

Use the same source name, replay name and detector selection on resume. Omitted
`-Detector` means the recorded selection was `both`, so keep an explicit AK02 or
SAP22 selection in later commands. Every profile override is forbidden on resume,
including an explicit default. A new command may select `-ElectronicsProfile` via
the existing strict settings contract. Resume uses the effective profile copied
into its manifest; later changes to the external profile path do not alter it.
All other run/setup/native overrides remain forbidden. Legacy one-shot and native
folders are never adopted. New output names must not already exist.

Dry-run is read-only: no Julia lookup/probe, output/lock creation or worker. Saved
progress inspection validates source pins, snapshots and every committed group,
and reports completed/expected counts. It does not certify loaded runtime readiness.
A completed resume is also read-only and idempotent: it validates the final bundle
without Julia or rewriting files, even with an invalid `JULIA_EXE` override.

## Files and transaction boundaries

The new `.local/replays/NEW/manifest.json` and immutable `INITIAL.json` bind the
complete original scalar/census ledger and signed `signals.csv` snapshots under
`inputs/`, copied original receipts, effective profile/configuration, software and
source hashes. The manifest defines the **exact full expected group set** before
electronics work; disk contents never determine which groups ought to exist.
All zero primaries remain in that complete ledger. Native failures retain their
null charge/response and exact original reason; no waveform is fabricated.

Each short group filename encodes detector/event/global-decay/group IDs. Its full
identity, source input hashes, group clock/origin/support, grid, ionisation units,
contact/model, configuration and runtime are bound through the immutable manifest
hash. `charge/KEY/` holds full signed-charge samples and original pulse metadata,
separate from `electronics/KEY/` results. Display traces never replace full charge.

Each commit stages data, flushes it to disk, writes a bound `PENDING.json`, then
atomically renames the directory and receipt to `COMMIT.json`. A separate immutable
`receipts/PHASE/KEY.json` binds the inner receipt, so deletion of a whole committed
data folder cannot turn it into apparently unstarted work. Hash, size, mtime,
identities, sample consistency, configuration/runtime and readout checks must pass
for **all** commits before new work. Corrupt or missing committed data is refused
and never recalculated. No old source pin can be rebased to resume changed code.

Unique `attempts/` stages, child logs, pending witnesses and failed outputs are
retained as noncommitted evidence. A canonical data directory missing either its
final receipt or separate witness is conservatively refused. The same applies to
final `worker/` data without `COMPLETE.json`. There is no orphan adoption or automatic
cleanup. A failure before `INITIAL.json` also requires inspection and a new name.
These boundaries trade automatic recovery for a clear, conservative first slice.

The existing exclusive source-run lease and a persistent output `run.lock` protect
concurrent starts/resumes. Locks are read-only exclusive opens on Windows, using
the existing conventions. The output lease is created only when a new root is
reserved; it is never deleted automatically. Cooperative leases cannot constrain
unrelated writers that ignore them. Atomic rename/fsync protects process-death
boundaries on the existing filesystem; this is not a power-loss or cloud-sync proof.

The driver owns progress, independent checks and final census. `run.json` is the
mutable status receipt; committed records determine saved progress after a crash.
`COMPLETE.json` is published only after all expected groups, zeros/native failures,
final aggregate artifacts and source checks reconcile. A child event or report
alone cannot claim completion. Final scalar/traces retain the M4b `worker/` layout.

## Numerical reuse and bounds

One runtime probe and **one sequential Julia worker per execution/resume** are
used, rather than a fresh Julia process for every group. The additive worker loads
only the existing readout/profile modules and M4b parser/runtime helpers. It never
loads SSD/native transport. One independent fixed-injection calibration is committed
per detector configuration, then verified and reused across groups/resumes. The
state transition matrix is reconstructed within the worker; calibration is not
recomputed when a committed one exists. No gain is fitted to truth Edep.

The unchanged `ReadoutProfiles.process` retains source units, signed policy,
inward-rounded peak gates and half-open 100 us support (last sample 99998 ns).
Independent M4b scalar/charge/current/ADC/gate checks are shared. Stored complete
support and step-limit flags are not proof of full physical collection or calibrated
Li CCE. The analog numerical grid is not waveform digitizer acquisition.

Existing M4a/M4b limits apply: 10,000 primaries, 2,000,000 full charge samples,
20,000,000 analog samples, 500,000 samples/group, 4 MiB JSON, 600 s worker and
4 MiB bounded child output; the checkpoint mode additionally caps 400 groups and
rejects unsupported Windows path lengths before reservation. Models/stages stay
serial, with two Julia threads and one BLAS thread in the child only. No service,
installation, environment or system defaults change.

## Validation and coordinator acceptance

```powershell
# Explicit source-only fixtures; mock runtime/electronics, retained evidence.
pvpython --no-mpi --disable-registry -B tools/test_group_checkpoints.py --evidence=.local/group-checkpoint-v1/implementation/NEW_SOFTWARE
# Coordinator after source freeze: exactly ONE new existing-host electronics derivative.
pvpython --no-mpi --disable-registry -B tools/test_group_checkpoints.py --host --replay-name=NEW_HOST_REPLAY --evidence=.local/group-checkpoint-v1/implementation/NEW_HOST_ACCEPTANCE
```

The host script stops the existing `custom-electronics-500-ak02-v1` import after
one group, checks immutable files, resumes to four groups and compares full scalar
records/calibration/traces with accepted `m4b-coordinator-host-v2-same` under the
predeclared M4b gates. It preserves the 500-primary/496-zero census, 20,008 samples,
IDs 213/220/325/450 and flags 26/88/35/59. It then checks completed resume with an
invalid Julia path and exact no-write behavior. The reference is never recomputed.
Actual acceptance on the owner's existing Windows host is recorded in
`.local/group-checkpoint-v1/host-verification-v2/COMPLETE.json`. One new derivative
was paused after one group, then after two, then completed at four across three
Julia sessions. Each group was requested once. Earlier group, charge, calibration,
input and commit-witness hashes/sizes/mtimes stayed unchanged. Full scalar records,
calibration and saved traces matched the previously accepted M4b reference.
Completed resume with an invalid Julia path was read-only and launched no Julia.

A second new test derivative used actual electronics with an instrumented driver
exit75 after the first verified group commit/status, before acknowledging the
worker. The Julia child exited when its parent pipe closed; no external kill was
needed. Public resume retained the first group and reproduced the reference.
This demonstrates ONE process-death boundary, not every power-loss/cloud-sync case.
The original source and accepted reference were not recalculated or rewritten.

Current software fixtures pass22 tests; electronics is explicitly mocked there.
Existing M4a88/M4b27/settings23 checks and dispatch also passed. All1835 baseline-
protected files remain exact. The first host attempt's local-variable shadowing
bug was fixed only in the additive worker; its failed derivative remains evidence.
Original numerical helpers, packages and global configuration were not changed.
M5b native-generation checkpoints and experimental/hardware validation remain open.

For a failed outer result, nested source-inspection fields describe preliminary
observations, not a final verification. Consumers must require the outer completed
status and verification_final; nested positive flags cannot authorize completion.
Clearing or explicitly relabelling those nested observations is a queued reporting
improvement, not a new recovery or numerical guarantee.
